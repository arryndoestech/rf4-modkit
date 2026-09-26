"""The Inspector tab: options for the active tool on top, and a form for whatever is
selected below (entity, warp, search spot, gate / monster point, or the tile under the
pointer when nothing is selected).

Every field commits on Enter or when it loses focus, as one undo step, and only when the
value actually changed. Forms re-read the document after every change (including undo),
so they never show stale values."""
from __future__ import annotations

import tkinter as tk
from collections import Counter
from tkinter import ttk

from rf4s_modkit import map_names, mobj_params, mobj_types

from . import attrs, data, ui
from .ui import commit_entry, hint, section


def mobj_choice(tid, name=None):
    return f"{tid}  {mobj_types.mobj_display_name(tid) or name or ''}".rstrip()


_MOBJ_CHOICES = None


def mobj_choices():
    """'<id>  <name>' for every placeable type: forage lanes, map parameters, sprites."""
    global _MOBJ_CHOICES
    if _MOBJ_CHOICES is None:
        out = [mobj_choice(t, mobj_params.FORAGE[t]["name"]) for t in sorted(mobj_params.FORAGE)]
        out += [mobj_choice(t, mobj_params.MAP_PARAMS[t]["name"]) for t in sorted(mobj_params.MAP_PARAMS)]
        out += [mobj_choice(t, n) for t, n in sorted(mobj_types.MOBJ_NAMES.items())]
        _MOBJ_CHOICES = out
    return _MOBJ_CHOICES


class Form(ttk.Frame):
    """Base for the selection forms: `show(key)` fills it, `refresh()` re-reads."""

    def __init__(self, parent, ed):
        super().__init__(parent)
        self.ed = ed
        self.key = None

    @property
    def doc(self):
        return self.ed.doc

    def show(self, key):
        self.key = key
        self.refresh()

    def refresh(self):
        pass

    def row(self, parent, label, var, on_commit, r, c=0, width=8, tip=None):
        ttk.Label(parent, text=label, font=ui.HINT_FONT).grid(row=r, column=c, sticky="w", padx=(0, 3))
        e = commit_entry(parent, var, on_commit, width=width)
        e.grid(row=r, column=c + 1, sticky="w", pady=1)
        if tip:
            ui.Tip(e, tip)
        return e


# --------------------------------------------------------------------------- #
# entity
# --------------------------------------------------------------------------- #
class EntityForm(Form):
    """One MOBJ record, laid out by what its type actually reads."""

    def __init__(self, parent, ed):
        super().__init__(parent, ed)
        self.title = ttk.Label(self, font=("Segoe UI", 10, "bold"))
        self.title.pack(anchor="w")
        self.sub = ttk.Label(self, font=ui.HINT_FONT, foreground=ui.MUTED)
        self.sub.pack(anchor="w")
        tr = ttk.Frame(self)
        tr.pack(fill="x", pady=(4, 0))
        ttk.Label(tr, text="Type").pack(side="left")
        self.type_combo = ui.FilterCombo(tr, mobj_choices(), self._pick_type, width=30)
        self.type_combo.pack(side="left", fill="x", expand=True, padx=(4, 0))
        ui.Tip(self.type_combo, "Type to filter by name or id; pick to change this entity's type.")
        self.type_label = ttk.Label(self, font=ui.HINT_FONT, foreground=ui.GOOD, wraplength=300,
                                    justify="left")
        self.type_label.pack(anchor="w", fill="x")

        g = ttk.Frame(self)
        g.pack(fill="x", pady=(4, 0))
        self.pos = ttk.Frame(g)
        self.pos.grid(row=0, column=0, sticky="w")
        self.vx, self.vy = tk.StringVar(), tk.StringVar()
        self.row(self.pos, "X", self.vx, self._commit_pos, 0, 0, 7,
                 tip="Sub-units: 8 per tile (tile = X >> 3).")
        self.row(self.pos, "Y", self.vy, self._commit_pos, 0, 2, 7)
        self.tile_lbl = ttk.Label(self.pos, font=ui.HINT_FONT, foreground=ui.MUTED)
        self.tile_lbl.grid(row=0, column=4, padx=4)
        self.st = ttk.Frame(g)
        self.st.grid(row=1, column=0, sticky="w")
        self.vscale, self.vrot = tk.StringVar(), tk.StringVar()
        self._f7 = "angle"                      # what f7 is for the shown type (mobj_f7_kind)
        self._tid = None
        self.row(self.st, "Scale", self.vscale, lambda: self._commit_field(6, self.vscale), 0, 0, 7,
                 tip=lambda: "f6 as a factor (1.0 = 4096); negative mirrors." + (
                     "" if self._tid is None or mobj_types.mobj_reads_scale(self._tid) else
                     "\nThis type ignores it in the game."))
        self.row(self.st, "Rotation °", self.vrot, lambda: self._commit_field(7, self.vrot), 0, 2, 7,
                 tip=lambda: {"angle": "f7 in degrees (stored as 65536 per turn).",
                              "frame": "f7: which frame of the sprite is shown."}.get(
                     self._f7, "f7: this type ignores it in the game."))
        self.scale_lbl = self.st.grid_slaves(row=0, column=0)[0]
        self.rot_lbl = self.st.grid_slaves(row=0, column=2)[0]

        self.pframe = ttk.Frame(self)
        self.pframe.pack(fill="x", pady=(4, 0))
        self.pframe.columnconfigure(2, weight=1)
        self.rows = []
        self._meanings = {}
        for fi in range(16):
            # the parameter's name; its explanation (and what the value means) is the tooltip
            var = tk.StringVar()
            lab = ttk.Label(self.pframe, font=ui.HINT_FONT)
            ent = commit_entry(self.pframe, var, lambda fi=fi: self._commit_param(fi), width=9)
            for w in (lab, ent):
                ui.Tip(w, lambda fi=fi: self._meanings.get(fi, ""))
            self.rows.append((lab, ent, var))
        self.raw = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="show all 16 raw fields", variable=self.raw,
                        command=self.refresh).pack(anchor="w", pady=(2, 0))
        self.role = ttk.Label(self, font=ui.SMALL_FONT, foreground=ui.MUTED, wraplength=300,
                              justify="left")
        self.role.pack(anchor="w", fill="x", pady=(2, 0))
        b = ttk.Frame(self)
        b.pack(fill="x", pady=(4, 2))
        ttk.Button(b, text="Center", width=7, command=lambda: ed.center_on(self.key)).pack(side="left")
        ttk.Button(b, text="Duplicate", width=9, command=lambda: ed.duplicate(self.key)).pack(side="left", padx=2)
        ttk.Button(b, text="Delete", width=7, command=lambda: ed.delete(self.key)).pack(side="left")
        ttk.Button(b, text="Flags…", width=7, command=ed.open_flag_reference).pack(side="right")

    # ---- values ---------------------------------------------------------- #
    def _rec(self):
        recs = self.doc.map.mobj_records()
        i = self.key[1]
        return list(recs[i]) if i < len(recs) else None

    def refresh(self):
        rec = self._rec()
        if rec is None:
            return
        i = self.key[1]
        tid = rec[0] & 0xFFFF
        o = self.doc.objs[i]
        mapparam = o["category"] == "mapparam"
        self.title.config(text=f"Entity #{i} · {mobj_types.mobj_display_name(tid) or f'type {tid}'}")
        self.sub.config(text=f"{o['category']} · " + ("map-wide parameter (no position)" if mapparam
                                                      else f"tile ({rec[14] >> 3}, {rec[15] >> 3})"))
        self.type_combo.var.set(mobj_choice(tid) if mobj_types.mobj_display_name(tid) else str(tid))
        name = mobj_types.mobj_name(tid)
        lab = mobj_types.mobj_label(tid)
        tex = mobj_types.mobj_texture(list(rec)) if tid >= 20 else None
        if tex and tex == name:
            lab += f"\nsprite map_obj/{name}.bntx (archive {mobj_types.mobj_archive_id(tid)})"
        elif tex:
            lab += f"\ntexture {tex}"
        elif name:
            lab += "\nno sprite of its own"
        self.type_label.config(text=lab)
        raw = self.raw.get()
        if mapparam or raw:
            self.pos.grid_remove()
            self.st.grid_remove()
        else:
            self.pos.grid()
            self.st.grid()
            self.vx.set(str(rec[14]))
            self.vy.set(str(rec[15]))
            self.tile_lbl.config(text=f"tile ({rec[14] >> 3}, {rec[15] >> 3})")
            self._tid, self._f7 = tid, mobj_types.mobj_f7_kind(tid)
            self.scale_lbl.config(text="Scale" if mobj_types.mobj_reads_scale(tid) else "Scale (unused)")
            self.rot_lbl.config(text={"angle": "Rotation °", "frame": "Frame"}.get(self._f7, "f7 (unused)"))
            self.vscale.set(self._fmt(6, rec[6]))
            self.vrot.set(self._fmt(7, rec[7]))
        try:
            role, described = mobj_params.describe(tid)
        except Exception:
            role, described = "", []
        meaning = {fi: (sz, m) for fi, sz, m in described}
        if raw:
            shown = list(range(16))
        else:
            shown = [fi for fi, _sz, _m in described if fi not in (0, 14, 15)
                     and not (fi in (6, 7) and not mapparam)]
        for fi, (lab_w, ent, var) in enumerate(self.rows):
            if fi not in shown:
                lab_w.grid_remove()
                ent.grid_remove()
                continue
            r = shown.index(fi)
            sz, m = meaning.get(fi, (4, ""))
            lab_w.config(text=mobj_params.param_name(tid, fi))
            lab_w.grid(row=r, column=0, sticky="w", padx=(0, 6))
            ent.grid(row=r, column=1, sticky="w", pady=1)
            eff = rec[fi] & ((1 << (8 * sz)) - 1)
            var.set(str(eff if sz < 4 else rec[fi]))
            head = f"word {fi}" + (f", read as {mobj_params.SIZE_NAME[sz]}" if sz != 4 else "")
            note = self._note(tid, fi, sz, m, eff, rec)
            self._meanings[fi] = head + ("\n" + note if note else "\n(the game doesn't read it)")
        only = "" if shown else "(position and type only -- this type reads no other fields)"
        try:
            inter = mobj_params.interaction_summary(tid, rec[13])
        except Exception:
            inter = ""
        self.role.config(text="\n".join(x for x in (role, f"interaction: {inter}" if inter else "", only) if x))

    def _note(self, tid, fi, sz, meaning, eff, rec):
        """What a field's value means: its description, flag names, ore config, and the
        other entities wired to the same flag."""
        parts = [meaning] if meaning else []
        if tid == 0 and fi == 10:
            cfg = data.ore_configs(self.ed.tex_reader)
            if 0 <= eff < len(cfg):
                kind, _d, _s, iw, rare = cfg[eff]
                ores = ", ".join(f"{data.item_name(it) or it}({w})" for it, w in iw if it)
                parts.append(f"= kind {kind}: {ores or 'empty row'}"
                             + (f", rare {data.item_name(rare) or rare}" if rare else ""))
        if "flag" in meaning.lower() and eff not in (0, 0xFFFF):
            fl = mobj_params.flag_label(eff)
            if fl:
                parts.append(f"= {fl}")
            shared = []
            recs = self.doc.map.mobj_records()
            for oi, orec in enumerate(recs):
                if oi == self.key[1]:
                    continue
                otid = orec[0] & 0xFFFF
                for pf, _ps, pm in mobj_params.params_for(otid):
                    if pf == 13 and "flag" in pm.lower() and (orec[13] & 0xFFFF) == eff:
                        shared.append(f"#{oi}")
                        break
            if shared:
                parts.append("same flag: " + ", ".join(shared[:6]))
        if (rec[fi] & 0xFFFFFFFF) != eff:
            parts.append(f"(raw 0x{rec[fi] & 0xFFFFFFFF:X}, low {mobj_params.SIZE_NAME[sz]} used)")
        return "\n".join(parts)

    def _fmt(self, fi, raw):
        if fi == 6:
            return f"{raw / 4096:g}"
        if fi == 7 and self._f7 == "angle":
            return f"{(raw % 65536) * 360 / 65536:g}"
        return str(raw)

    # ---- commits --------------------------------------------------------- #
    def _set(self, rec, label):
        self.ed.apply(label, "mobj", lambda: self.doc.map.set_mobj_record(self.key[1], rec))

    def _commit_pos(self):
        rec = self._rec()
        x, y = ui.to_int(self.vx.get()), ui.to_int(self.vy.get())
        if rec is None or x is None or y is None or (x, y) == (rec[14], rec[15]):
            return
        rec[14], rec[15] = x, y
        self._set(rec, f"Move entity #{self.key[1]}")

    def _commit_field(self, fi, var):
        rec = self._rec()
        if rec is None or var.get().strip() == self._fmt(fi, rec[fi]):
            return
        try:
            v = float(var.get())
        except ValueError:
            return
        if fi == 6:
            rec[fi] = int(round(v * 4096))
        elif self._f7 == "angle":
            rec[fi] = int(round(v * 65536 / 360)) % 65536
        else:
            rec[fi] = int(round(v))
        what = "scale" if fi == 6 else {"angle": "rotation", "frame": "frame"}.get(self._f7, "f7")
        self._set(rec, f"Set entity #{self.key[1]} {what}")

    def _commit_param(self, fi):
        rec = self._rec()
        if rec is None:
            return
        v = ui.to_int(self.rows[fi][2].get())
        if v is None:
            return
        tid = rec[0] & 0xFFFF
        sz = mobj_params.field_size(tid, fi) if not self.raw.get() else 4
        sz = sz or 4
        if sz < 4:
            mask = (1 << (8 * sz)) - 1
            new = (rec[fi] & ~mask) | (v & mask)
        else:
            new = v
        if new == rec[fi]:
            return
        rec[fi] = new
        self._set(rec, f"Set entity #{self.key[1]} f{fi}")

    def _pick_type(self, text):
        tid = data.leading_int(text)
        rec = self._rec()
        if rec is None or tid is None or tid == (rec[0] & 0xFFFF):
            return
        rec[0] = (rec[0] & ~0xFFFF) | (tid & 0xFFFF)
        self._set(rec, f"Change entity #{self.key[1]} type to {tid}")


# --------------------------------------------------------------------------- #
# warp
# --------------------------------------------------------------------------- #
class WarpForm(Form):
    FIELDS = (("x", 1), ("y", 2), ("w", 3), ("h", 4), ("ax", 6), ("ay", 7), ("face", 8))

    def __init__(self, parent, ed):
        super().__init__(parent, ed)
        self.title = ttk.Label(self, font=("Segoe UI", 10, "bold"))
        self.title.pack(anchor="w")
        self.sub = ttk.Label(self, font=ui.HINT_FONT, foreground=ui.MUTED, wraplength=300)
        self.sub.pack(anchor="w")
        self.v = {k: tk.StringVar() for k, _ in self.FIELDS}
        z = ttk.LabelFrame(self, text="Trigger zone (sub-units, 8 per tile)", padding=4)
        z.pack(fill="x", pady=(4, 0))
        self.row(z, "x", self.v["x"], self._commit, 0, 0, 6)
        self.row(z, "y", self.v["y"], self._commit, 0, 2, 6)
        self.row(z, "w", self.v["w"], self._commit, 1, 0, 6)
        self.row(z, "h", self.v["h"], self._commit, 1, 2, 6)
        self.zone_lbl = ttk.Label(z, font=ui.HINT_FONT, foreground=ui.MUTED)
        self.zone_lbl.grid(row=2, column=0, columnspan=4, sticky="w")
        d = ttk.LabelFrame(self, text="Destination", padding=4)
        d.pack(fill="x", pady=(4, 0))
        self.dest = ui.FilterCombo(d, data.map_choices(), lambda _t: self._commit(), width=34)
        self.dest.grid(row=0, column=0, columnspan=4, sticky="we", pady=(0, 2))
        ui.Tip(self.dest, "Type part of a map name or id to filter; a bare id works too.")
        self.dest.bind("<FocusOut>", lambda _e: self._commit(), add="+")
        self.dest._commit = self._commit
        self.row(d, "arrive x", self.v["ax"], self._commit, 1, 0, 6,
                 tip="Arrival position in the destination map, sub-units.")
        self.row(d, "arrive y", self.v["ay"], self._commit, 1, 2, 6)
        self.row(d, "facing °", self.v["face"], self._commit, 2, 0, 6,
                 tip="Arrival facing in degrees; 0 keeps the current facing.")
        f = ttk.Frame(self)
        f.pack(fill="x", pady=(4, 0))
        self.always = tk.BooleanVar()
        ttk.Checkbutton(f, text="always active", variable=self.always,
                        command=self._toggle_always).pack(side="left")
        ttk.Label(f, text="  off while flag").pack(side="left")
        self.vflag = tk.StringVar()
        self.flag_e = commit_entry(f, self.vflag, self._commit, width=6)
        self.flag_e.pack(side="left", padx=2)
        ui.Tip(self.flag_e, "Per-map scene flag (absolute 4096 + id) that DISABLES the warp while "
                            "it is set. The castle exits use 632, for example.")
        b = ttk.Frame(self)
        b.pack(fill="x", pady=(6, 2))
        ttk.Button(b, text="Open destination", command=lambda: ed.goto_warp(self.key[1])).pack(side="left")
        ttk.Button(b, text="Center", width=7, command=lambda: ed.center_on(self.key)).pack(side="left", padx=2)
        ttk.Button(b, text="Duplicate", width=9, command=lambda: ed.duplicate(self.key)).pack(side="left")
        ttk.Button(b, text="Delete", width=7, command=lambda: ed.delete(self.key)).pack(side="left", padx=2)

    def _rec(self):
        recs = self.doc.map.mapj_records()
        j = self.key[1]
        return list(recs[j]) if j < len(recs) else None

    def refresh(self):
        rec = self._rec()
        if rec is None:
            return
        j = self.key[1]
        place = map_names.describe_destination(rec[5])[0]
        self.title.config(text=f"Warp #{j} → {place or data.rooms_by_id().get(rec[5], f'map {rec[5]}')}")
        self.sub.config(text=data.map_choice(rec[5]))
        for k, idx in self.FIELDS:
            self.v[k].set(str(rec[idx]))
        self.zone_lbl.config(text=f"tiles ({rec[1] >> 3}, {rec[2] >> 3}) .. "
                                  f"({(rec[1] + rec[3]) >> 3}, {(rec[2] + rec[4]) >> 3})")
        self.dest.var.set(data.map_choice(rec[5]) if rec[5] in data.rooms_by_id() else str(rec[5]))
        self.always.set(rec[0] == -1)
        self.vflag.set("" if rec[0] == -1 else str(rec[0]))
        self.flag_e.config(state="disabled" if rec[0] == -1 else "normal")

    def _toggle_always(self):
        rec = self._rec()
        if rec is None:
            return
        if self.always.get():
            rec[0] = -1
        else:
            rec[0] = ui.to_int(self.vflag.get(), 0) if self.vflag.get().strip() else 0
        self.ed.apply(f"Set warp #{self.key[1]} flag", "mapj",
                      lambda: self.doc.map.set_mapj_record(self.key[1], rec))

    def _commit(self):
        rec = self._rec()
        if rec is None:
            return
        new = list(rec)
        for k, idx in self.FIELDS:
            v = ui.to_int(self.v[k].get())
            if v is None:
                return
            new[idx] = v
        dm = data.leading_int(self.dest.var.get())
        if dm is None:
            return
        new[5] = dm
        if not self.always.get():
            fl = ui.to_int(self.vflag.get())
            if fl is not None:
                new[0] = fl
        if new == rec:
            return
        self.ed.apply(f"Edit warp #{self.key[1]}", "mapj",
                      lambda: self.doc.map.set_mapj_record(self.key[1], new))


# --------------------------------------------------------------------------- #
# search spot
# --------------------------------------------------------------------------- #
class SpotForm(Form):
    def __init__(self, parent, ed):
        super().__init__(parent, ed)
        self.title = ttk.Label(self, font=("Segoe UI", 10, "bold"))
        self.title.pack(anchor="w")
        self.sub = ttk.Label(self, font=ui.HINT_FONT, foreground=ui.MUTED)
        self.sub.pack(anchor="w")
        p = ttk.Frame(self)
        p.pack(fill="x", pady=(4, 0))
        self.vx, self.vy = tk.StringVar(), tk.StringVar()
        self.row(p, "X", self.vx, self._commit_pos, 0, 0, 7, tip="Sub-units: 8 per tile.")
        self.row(p, "Y", self.vy, self._commit_pos, 0, 2, 7)
        ttk.Label(self, text="Drop pool").pack(anchor="w", pady=(6, 0))
        self.pool = ttk.Treeview(self, columns=("id", "name", "w", "pct"), show="headings", height=6,
                                 selectmode="browse")
        for c, t, w, a in (("id", "id", 44, "e"), ("name", "item", 140, "w"), ("w", "weight", 50, "e"),
                           ("pct", "chance", 56, "e")):
            self.pool.heading(c, text=t)
            self.pool.column(c, width=w, anchor=a, stretch=(c == "name"))
        self.pool.pack(fill="x")
        self.pool.bind("<<TreeviewSelect>>", self._pool_pick)
        e = ttk.Frame(self)
        e.pack(fill="x", pady=(2, 0))
        self.item = ui.FilterCombo(e, data.item_choices(), None, width=24)
        self.item.pack(side="left", fill="x", expand=True)
        ui.Tip(self.item, "Item: type part of a name or an id.")
        ttk.Label(e, text=" w").pack(side="left")
        self.vw = tk.StringVar(value="10")
        ttk.Entry(e, textvariable=self.vw, width=4).pack(side="left")
        b = ttk.Frame(self)
        b.pack(fill="x", pady=(2, 0))
        ttk.Button(b, text="Add item", command=self._add).pack(side="left")
        ttk.Button(b, text="Replace", command=self._replace).pack(side="left", padx=2)
        ttk.Button(b, text="Remove", command=self._remove).pack(side="left")
        self.total = ttk.Label(self, font=ui.HINT_FONT, wraplength=300, justify="left")
        self.total.pack(anchor="w", pady=(2, 0))
        b2 = ttk.Frame(self)
        b2.pack(fill="x", pady=(4, 2))
        ttk.Button(b2, text="Center", width=7, command=lambda: ed.center_on(self.key)).pack(side="left")
        ttk.Button(b2, text="Duplicate", width=9, command=lambda: ed.duplicate(self.key)).pack(side="left", padx=2)
        ttk.Button(b2, text="Delete spot", command=lambda: ed.delete(self.key)).pack(side="left")
        hint(self, "Daily ground pickups: up to two spots spawn per day (sleeping rerolls). "
                   "item = entry & 0x7FF, weight = one byte. Stock files share one pool between "
                   "spots; editing a spot here gives it its own copy.").pack(anchor="w", pady=(4, 0))

    def _spot(self):
        si = self.doc.si
        i = self.key[1]
        return si.spots[i] if si is not None and i < len(si.spots) else None

    def refresh(self):
        sp = self._spot()
        if sp is None:
            return
        self.title.config(text=f"Search spot #{self.key[1]}")
        self.sub.config(text=f"tile ({sp.tile_x}, {sp.tile_y}) · "
                             f"{self.doc.si_path.name if self.doc.si_path else 'new SI file'}")
        self.vx.set(str(sp.x))
        self.vy.set(str(sp.y))
        keep = self.pool.selection()
        self.pool.delete(*self.pool.get_children())
        ents = sp.pool.entries
        total = sum(e.effective_weight for e in ents)
        for k, e in enumerate(ents):
            iid = e.effective_item_id
            pct = 100.0 * e.effective_weight / total if total else 0
            self.pool.insert("", "end", iid=str(k), values=(iid, data.item_name(iid) or "?",
                                                            e.effective_weight, f"{pct:.1f}%"))
        if keep and self.pool.exists(keep[0]):
            self.pool.selection_set(keep[0])
        warn = ""
        if total > 255:
            warn = f"  ⚠ the game sums weights in one byte: {total} wraps to {total & 0xFF}"
        self.total.config(text=f"{len(ents)} item(s), total weight {total}{warn}",
                          foreground="#c60" if warn else "")

    def _commit_pos(self):
        sp = self._spot()
        x, y = ui.to_int(self.vx.get()), ui.to_int(self.vy.get())
        if sp is None or x is None or y is None or (x & 0xFFFF, y & 0xFFFF) == (sp.x, sp.y):
            return

        def do():
            sp2 = self.doc.si.spots[self.key[1]]
            sp2.x, sp2.y = x & 0xFFFF, y & 0xFFFF
        self.ed.apply(f"Move search spot #{self.key[1]}", "si", do)

    def _pool_pick(self, _e=None):
        s = self.pool.selection()
        sp = self._spot()
        if not s or sp is None:
            return
        e = sp.pool.entries[int(s[0])]
        iid = e.effective_item_id
        self.item.var.set(f"{iid}  {data.item_name(iid)}".rstrip())
        self.vw.set(str(e.effective_weight))

    def _entry_values(self):
        iid = data.leading_int(self.item.var.get())
        w = ui.to_int(self.vw.get())
        if iid is None or w is None:
            self.ed.status("Pick an item and a weight first.")
            return None
        return iid & 0x7FF, w & 0xFF

    def _add(self):
        v = self._entry_values()
        if v is None:
            return
        from rf4s_modkit import search_items

        def do():
            self.doc.si.spots[self.key[1]].pool.entries.append(
                search_items.DropEntry(item_id=v[0], weight=v[1] or 1))
        self.ed.apply(f"Add item {v[0]} to spot #{self.key[1]}", "si", do)

    def _replace(self):
        s = self.pool.selection()
        v = self._entry_values()
        if not s or v is None:
            return

        def do():
            e = self.doc.si.spots[self.key[1]].pool.entries[int(s[0])]
            e.item_id, e.weight = v
        self.ed.apply(f"Edit spot #{self.key[1]} drop", "si", do)

    def _remove(self):
        s = self.pool.selection()
        if not s:
            return

        def do():
            del self.doc.si.spots[self.key[1]].pool.entries[int(s[0])]
        self.ed.apply(f"Remove drop from spot #{self.key[1]}", "si", do)


# --------------------------------------------------------------------------- #
# gate position / monster spawn point
# --------------------------------------------------------------------------- #
class PointForm(Form):
    def __init__(self, parent, ed):
        super().__init__(parent, ed)
        self.title = ttk.Label(self, font=("Segoe UI", 10, "bold"))
        self.title.pack(anchor="w")
        self.sub = ttk.Label(self, font=ui.HINT_FONT, foreground=ui.MUTED, wraplength=300,
                             justify="left")
        self.sub.pack(anchor="w")
        p = ttk.Frame(self)
        p.pack(fill="x", pady=(4, 0))
        self.vx, self.vy = tk.StringVar(), tk.StringVar()
        self.row(p, "X", self.vx, self._commit, 0, 0, 7, tip="Sub-units: 8 per tile.")
        self.row(p, "Y", self.vy, self._commit, 0, 2, 7)
        b = ttk.Frame(self)
        b.pack(fill="x", pady=(6, 2))
        ttk.Button(b, text="Show gate", command=self._show_gate).pack(side="left")
        ttk.Button(b, text="Center", width=7, command=lambda: ed.center_on(self.key)).pack(side="left", padx=2)
        ttk.Button(b, text="Delete point", command=lambda: ed.delete(self.key)).pack(side="left")
        self.note = hint(self, "")
        self.note.pack(anchor="w", pady=(4, 0))

    def _point(self):
        for pk, off, x, y, users in self.doc.gate_points():
            if (pk, off) == tuple(self.key):
                return x, y, users
        return None

    def refresh(self):
        p = self._point()
        if p is None:
            return
        x, y, users = p
        kind = self.key[0]
        self.title.config(text="Gate position" if kind == "gpos" else "Monster spawn point")
        names = []
        for pi, ei in users[:6]:
            e = self.doc.gen.patterns[pi][ei]
            names.append(f"gate {e.gate_kind} {data.actor_name(e.gate_kind)}".strip())
        self.sub.config(text=f"tile ({x >> 3}, {y >> 3}) · used by {len(users)} gate(s): "
                             + ", ".join(names) + ("…" if len(users) > 6 else ""))
        self.vx.set(str(x))
        self.vy.set(str(y))
        self.note.config(text=("One of the places the gate actor can appear; the spawner picks "
                               "one at random." if kind == "gpos" else
                               "Where the gate's monsters appear. Each roster monster has one "
                               "weight per spawn point."))

    def _commit(self):
        p = self._point()
        x, y = ui.to_int(self.vx.get()), ui.to_int(self.vy.get())
        if p is None or x is None or y is None or (x, y) == (p[0], p[1]):
            return
        self.ed.set_position_edit(tuple(self.key), (x, y))

    def _show_gate(self):
        p = self._point()
        if p and p[2]:
            self.ed.show_gate(p[2][0])


# --------------------------------------------------------------------------- #
# nothing selected: the tile under the pointer
# --------------------------------------------------------------------------- #
class TileForm(Form):
    def __init__(self, parent, ed):
        super().__init__(parent, ed)
        ttk.Label(self, text="Nothing selected", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        hint(self, "Click an entity, warp, search spot or gate marker on the map, or pick one "
                   "in the Objects tab.").pack(anchor="w")
        self.tile = ttk.Label(self, font=ui.MONO, justify="left", wraplength=310)
        self.tile.pack(anchor="w", pady=(6, 0))
        self.use = ttk.Button(self, text="Paint with this value", command=self._use)
        self.use.pack(anchor="w", pady=(2, 0))
        self._val = None

    def hover(self, t):
        d = self.doc
        if d is None or t is None or d.grid is None:
            return
        v = d.cell(*t)
        self._val = v
        self.tile.config(text=f"tile ({t[0]}, {t[1]})\nATTR 0x{v:X}\n{attrs.attr_notes(v)}")

    def _use(self):
        if self._val is not None:
            self.ed.set_paint_value(self._val)
            self.ed.set_tool("paint")


# --------------------------------------------------------------------------- #
# tool options
# --------------------------------------------------------------------------- #
class PaintOptions(ttk.Frame):
    """The shared ATTR value for Paint / Fill / Rectangle, as flags + surface + raw hex."""

    def __init__(self, parent, ed):
        super().__init__(parent)
        self.ed = ed
        r = ttk.Frame(self)
        r.pack(fill="x")
        ttk.Label(r, text="Value").pack(side="left")
        self.vval = tk.StringVar(value="0x1")
        self.val_e = commit_entry(r, self.vval, self._from_entry, width=12)
        self.val_e.pack(side="left", padx=4)
        self.swatch = tk.Label(r, width=3, relief="solid", bd=1)
        self.swatch.pack(side="left")
        self.brush_row = ttk.Frame(r)
        self.brush_row.pack(side="right")
        ttk.Label(self.brush_row, text="brush").pack(side="left")
        self.vbrush = tk.StringVar(value="1")
        sb = ttk.Combobox(self.brush_row, textvariable=self.vbrush, values=("1", "2", "3", "5", "7", "9"),
                          width=3, state="readonly")
        sb.pack(side="left", padx=(3, 0))
        sb.bind("<<ComboboxSelected>>", lambda _e: ed.set_brush(int(self.vbrush.get())))
        self.decode = ttk.Label(self, font=ui.HINT_FONT, foreground=ui.GOOD, wraplength=310, justify="left")
        self.decode.pack(anchor="w", fill="x")
        self.global_fill = tk.BooleanVar(value=False)
        self.global_cb = ttk.Checkbutton(self, text="Fill: replace this value on the whole map",
                                         variable=self.global_fill,
                                         command=lambda: setattr(ed, "fill_global", self.global_fill.get()))
        fg = ttk.Frame(self)
        fg.pack(fill="x", pady=(4, 0))
        self.bits = {}
        for i, (nm, mask) in enumerate(attrs.PAINT_FLAGS):
            bv = tk.BooleanVar()
            self.bits[mask] = bv
            cb = ttk.Checkbutton(fg, text=nm, variable=bv, command=self._from_controls)
            cb.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 4))
            ui.Tip(cb, attrs.attr_bit_help(mask))
        sr = ttk.Frame(self)
        sr.pack(fill="x", pady=(3, 0))
        ttk.Label(sr, text="surface").pack(side="left")
        self.vsurf = tk.StringVar(value="(none)")
        sc = ttk.Combobox(sr, textvariable=self.vsurf, values=[c[0] for c in attrs.SURFACE_CHOICES],
                          width=15, state="readonly")
        sc.pack(side="left", padx=4)
        sc.bind("<<ComboboxSelected>>", lambda _e: self._from_controls())
        ui.Tip(sc, attrs.surface_help())
        hint(sr, "one at most", wrap=120).pack(side="left")
        pr = ttk.Frame(self)
        pr.pack(fill="x", pady=(3, 0))
        for label, v in attrs.PAINT_PRESETS:
            ttk.Button(pr, text=label, width=len(label) + 1,
                       command=lambda v=v: ed.set_paint_value(v)).pack(side="left", padx=(0, 2))
        hint(self, "Hover a flag for what the game does with it.").pack(anchor="w", pady=(2, 0))
        ttk.Label(self, text="Values in this map (click to use)").pack(anchor="w", pady=(6, 0))
        tv = ttk.Treeview(self, columns=("v", "n", "d"), show="headings", height=7, selectmode="browse")
        for c, t, w, a in (("v", "value", 84, "w"), ("n", "tiles", 50, "e"), ("d", "meaning", 170, "w")):
            tv.heading(c, text=t)
            tv.column(c, width=w, anchor=a, stretch=(c == "d"))
        tv.pack(fill="x")
        tv.bind("<<TreeviewSelect>>", self._pick_row)
        self.values = tv
        self._values_for = None

    def show_for(self, tool):
        self.brush_row.pack_forget()
        self.global_cb.pack_forget()
        if tool == "paint":
            self.brush_row.pack(side="right")
        if tool == "fill":
            self.global_cb.pack(anchor="w", after=self.decode)

    def sync(self, value, colors):
        """Reflect the editor's paint value in every control."""
        self.vval.set(f"0x{value:X}")
        for mask, bv in self.bits.items():
            bv.set(bool(value & mask))
        self.vsurf.set(attrs.surface_label(value))
        self.decode.config(text=attrs.attr_notes(value))
        rgb = colors.get(value)
        self.swatch.config(bg="#%02x%02x%02x" % rgb if rgb else "#000000")

    def _from_entry(self):
        v = attrs.parse_value(self.vval.get())
        if v is None:
            self.decode.config(text="(not a number)")
            return
        self.ed.set_paint_value(v)

    def _from_controls(self):
        cur = self.ed.paint_value or 0
        flags = {m for m, bv in self.bits.items() if bv.get()}
        self.ed.set_paint_value(attrs.compose_value(cur, flags, self.vsurf.get()))

    def fill_values(self, doc, colors):
        """The value table for `doc` (rebuilt only when the grid changed)."""
        key = (id(doc), doc.attr_version if doc else None)
        if key == self._values_for or doc is None or doc.grid is None:
            return
        self._values_for = key
        tv = self.values
        tv.delete(*tv.get_children())
        for v, n in Counter(doc.grid[2]).most_common():
            tag = f"c{v:x}"
            rgb = colors.get(v, attrs.ATTR_FLOOR)
            lum = 0.3 * rgb[0] + 0.59 * rgb[1] + 0.11 * rgb[2]
            tv.tag_configure(tag, background="#%02x%02x%02x" % rgb,
                             foreground="#000" if lum > 110 else "#fff")
            tv.insert("", "end", iid=str(v), values=(f"0x{v:X}", n, attrs.attr_notes(v)), tags=(tag,))

    def _pick_row(self, _e=None):
        s = self.values.selection()
        if s:
            self.ed.set_paint_value(int(s[0]))


class AddOptions(ttk.Frame):
    KINDS = (("entity", "Entity"), ("spot", "Search spot"), ("gpos", "Gate position"),
             ("mpos", "Monster spawn point"))

    def __init__(self, parent, ed):
        super().__init__(parent)
        self.ed = ed
        self.vkind = tk.StringVar(value="entity")
        kr = ttk.Frame(self)
        kr.pack(fill="x")
        for i, (k, lab) in enumerate(self.KINDS):
            ttk.Radiobutton(kr, text=lab, value=k, variable=self.vkind,
                            command=lambda: ed.set_add_kind(self.vkind.get())).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 8))
        self.ent = ttk.Frame(self)
        ttk.Label(self.ent, text="Type").pack(side="left")
        self.type_combo = ui.FilterCombo(self.ent, mobj_choices(), self._pick, width=30)
        self.type_combo.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.type_lbl = ttk.Label(self, font=ui.HINT_FONT, foreground=ui.GOOD, wraplength=310, justify="left")
        self.note = hint(self, "")
        self._pick(mobj_choice(28))

    def _pick(self, text):
        tid = data.leading_int(text)
        if tid is None:
            return
        self.type_combo.var.set(mobj_choice(tid))
        self.ed.add_type = tid
        self.type_lbl.config(text=mobj_types.mobj_label(tid))

    def sync(self):
        k = self.ed.add_kind
        self.vkind.set(k)
        for w in (self.ent, self.type_lbl, self.note):
            w.pack_forget()
        if k == "entity":
            self.ent.pack(fill="x", pady=(4, 0))
            self.type_lbl.pack(anchor="w", fill="x")
        elif k in ("gpos", "mpos"):
            g = self.ed.active_gate
            self.note.config(text=(f"Adds to gate {g.gate_kind} {data.actor_name(g.gate_kind)}"
                                   if g is not None else
                                   "Select a gate in the Gates tab first: the point is added "
                                   "to that gate."))
            self.note.pack(anchor="w", pady=(4, 0))
        else:
            self.note.config(text="Adds a spot with an empty drop pool to this map's SI file "
                                  "(created if the map has none).")
            self.note.pack(anchor="w", pady=(4, 0))


# --------------------------------------------------------------------------- #
class Inspector(ui.ScrollFrame):
    def __init__(self, parent, ed):
        super().__init__(parent)
        self.ed = ed
        b = self.body
        tool_box = section(b, "Tool")
        self.tool_title = ttk.Label(tool_box, font=("Segoe UI", 9, "bold"))
        self.tool_title.pack(anchor="w")
        self.tool_hint = hint(tool_box, "")
        self.tool_hint.pack(anchor="w", fill="x")
        self.paint = PaintOptions(tool_box, ed)
        self.add = AddOptions(tool_box, ed)
        self.sel_box = section(b, "Selection")
        self.forms = {"mobj": EntityForm(self.sel_box, ed), "warp": WarpForm(self.sel_box, ed),
                      "si": SpotForm(self.sel_box, ed), "gpos": PointForm(self.sel_box, ed),
                      "none": TileForm(self.sel_box, ed)}
        self.forms["mpos"] = self.forms["gpos"]
        self._form = None
        self._tool = None
        self.show_selection(None)
        self.bind_wheel_tree()

    def show_tool(self, tool):
        self.tool_title.config(text=f"{tool.label}  ({tool.key.upper()})")
        self.tool_hint.config(text=tool.hint)
        if tool.name == self._tool:
            return
        self._tool = tool.name
        self.paint.pack_forget()
        self.add.pack_forget()
        if tool.name in ("paint", "fill", "rect", "pick"):
            self.paint.show_for(tool.name)
            self.paint.pack(fill="x", pady=(4, 0))
            self.paint.fill_values(self.ed.doc, self.ed.view.colors)
        elif tool.name == "add":
            self.add.sync()
            self.add.pack(fill="x", pady=(4, 0))

    def show_selection(self, key):
        form = self.forms["none" if key is None else key[0]]
        if form is not self._form:
            if self._form is not None:
                self._form.pack_forget()
            form.pack(fill="x")
            self._form = form
        if key is not None:
            form.show(key)
        else:
            form.key = None

    def refresh(self, aspects=frozenset()):
        if self._form is not None and self._form.key is not None:
            self._form.refresh()
        if "attr" in aspects and self._tool in ("paint", "fill", "rect", "pick"):
            self.paint.fill_values(self.ed.doc, self.ed.view.colors)
        if self._tool == "add":
            self.add.sync()

    def hover(self, t):
        if self._form is self.forms["none"]:
            self.forms["none"].hover(t)
