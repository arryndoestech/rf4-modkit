"""The Event Manager window: browse em.bin's entries (conditions -> actions) and the
game-state queries, edit condition thresholds / operators and action values in place,
add or remove entries, and add or remove whole conditions and actions from text.

Every change goes through the document, so it is undoable and em.bin counts as unsaved
until saved (it used to be neither)."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from guiutil import Paned, Tip, set_text
from rf4s_modkit import emscript, script

from . import catalog

EM_ARITH_OPS = ["SET", "ADD", "SUB", "MUL_S", "MUL_U", "DIV_S", "DIV_U",
                "MOD_S", "MOD_U", "MAX_S", "MAX_U", "MIN_S", "MIN_U", "SET_EQ_ZERO"]


def parse_condition(em, entry, text):
    """('a'|'b', slot|None, [Expr]) from a condition spec. A leading `B:` targets
    condition B; `slot=N ` ANDs the terms onto OR-slot N instead of opening a new one."""
    t = (text or "").strip()
    which = "a"
    if t[:2].lower() == "b:":
        which, t = "b", t[2:].strip()
    elif t[:2].lower() == "a:":
        t = t[2:].strip()
    slot = None
    m = re.match(r"slot\s*=\s*(\d+)\s+(.*)$", t, re.I)
    if m:
        slot, t = int(m.group(1)), m.group(2).strip()
        slots = (entry.cond_a if which == "a" else entry.cond_b) or []
        if not 0 <= slot <= len(slots):
            raise ValueError("condition %s has %d OR-slot(s); slot=%d is out of range (omit slot= "
                             "to open a new one)" % (which.upper(), len(slots), slot))
    if not t:
        raise ValueError("no condition terms")
    return which, slot, em.parse_condition_spec(t)


def parse_action(em, text):
    """('main'|'alt', Action) from an action spec; a leading `alt:` picks the alt stream."""
    t = (text or "").strip()
    stream = "main"
    if t[:4].lower() == "alt:":
        stream, t = "alt", t[4:].strip()
    elif t[:5].lower() == "main:":
        t = t[5:].strip()
    if not t:
        raise ValueError("no action")
    return stream, em.parse_action_spec(t)


def editable_fields(em, e):
    """Each comparison (its literal + operator) and each arithmetic action (value + op)."""
    fields = []
    for which, slots in (("A", e.cond_a), ("B", e.cond_b)):
        for si, exprs in enumerate(slots or []):
            for xi, x in enumerate(exprs):
                if x.kind != "cmp":
                    continue
                lit = (x.op2 if (x.op2 and x.op2.kind in ("lit", "slit")) else
                       (x.op1 if (x.op1 and x.op1.kind in ("lit", "slit")) else None))
                fields.append({"label": "cond%s[%d.%d]  %s" % (which, si, xi, x.pretty(em.names)),
                               "path": ("cond", which, si, xi), "val": lit.value if lit else None,
                               "has_val": lit is not None, "op": x.cmp, "ops": ["==", "!=", ">", ">="]})
    for area, acts in (("main", e.actions), ("alt", e.alt_actions)):
        for ai, a in enumerate(acts or []):
            if a.name == "CALL":
                continue
            v = a.value
            fields.append({"label": "%s[%d]  %s" % (area, ai, a.pretty(em.names)),
                           "path": ("act", area, ai, None), "val": v.value if v else None,
                           "has_val": bool(v and v.kind in ("lit", "slit", "query")),
                           "op": a.name, "ops": EM_ARITH_OPS})
    return fields


def _resolve(em, idx, path):
    """The live Expr / Action object a field path names (objects are rebuilt by relayouts)."""
    e = em.entries[idx]
    kind, which, a, b = path
    if kind == "cond":
        x = ((e.cond_a if which == "A" else e.cond_b) or [])[a][b]
        lit = (x.op2 if (x.op2 and x.op2.kind in ("lit", "slit")) else
               (x.op1 if (x.op1 and x.op1.kind in ("lit", "slit")) else None))
        return x, lit
    act = (e.actions if which == "main" else e.alt_actions)[a]
    v = act.value
    return act, (v if (v and v.kind in ("lit", "slit", "query")) else None)


class EventManagerWindow:
    def __init__(self, app):
        self.app = app
        self.doc = app.doc
        em = self.em
        self.win = win = tk.Toplevel(app.frame)
        win.title("Event Manager (em.bin) — %d entries" % len(em.entries))
        win.geometry("1020x600")
        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True)
        tab = ttk.Frame(nb)
        nb.add(tab, text="Entries")
        top = ttk.Frame(tab)
        top.pack(fill="x")
        ttk.Label(top, text="Filter").pack(side="left", padx=4)
        self.flt = tk.StringVar()
        fe = ttk.Entry(top, textvariable=self.flt, width=30)
        fe.pack(side="left", pady=3)
        Tip(fe, "Matches an entry's name, JP label and decoded body: type REG_WIFE_ID, a flag, a "
                "query name or an entry number to find everything that uses it.")
        ttk.Label(top, text="A = condition A · B = condition B · ! = actions · ~ = alt actions",
                  foreground="#666").pack(side="left", padx=10)
        rm = ttk.Button(top, text="Remove entry", command=self.remove_entry)
        rm.pack(side="right", padx=3)
        Tip(rm, "Delete the selected entry; later ids move down one (internal references are "
                "renumbered, rf3.mc bridge ops are NOT). Offers to clear it in place instead when "
                "other entries reference it.")
        ad = ttk.Button(top, text="Add entry", command=self.add_entry)
        ad.pack(side="right", padx=3)
        Tip(ad, "Append a new entry (empty, or a copy of the selected one). Its id is the old count.")
        pane = Paned(tab, orient="horizontal")
        pane.pack(fill="both", expand=True)
        lf = ttk.Frame(pane)
        pane.add(lf, weight=1, width=320)
        self.lb = tk.Listbox(lf, font=("Consolas", 9), exportselection=False)
        sb = ttk.Scrollbar(lf, command=self.lb.yview)
        self.lb.config(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        rf = ttk.Frame(pane)
        pane.add(rf, weight=2)
        self.detail = tk.Text(rf, font=("Consolas", 9), wrap="word", state="disabled", height=14)
        self.detail.pack(fill="both", expand=True)
        ttk.Label(rf, text="used by scenes (double-click to open):", foreground="#888").pack(anchor="w", padx=2)
        uf = ttk.Frame(rf)
        uf.pack(fill="x")
        self.uses = tk.Listbox(uf, font=("Consolas", 9), height=6, exportselection=False)
        usb = ttk.Scrollbar(uf, command=self.uses.yview)
        self.uses.config(yscrollcommand=usb.set)
        self.uses.pack(side="left", fill="both", expand=True)
        usb.pack(side="left", fill="y")
        # value / operator edit
        ef = ttk.LabelFrame(rf, text="Change a value or operator")
        ef.pack(fill="x", pady=3)
        self.field_cb = ttk.Combobox(ef, state="readonly", width=60)
        self.field_cb.grid(row=0, column=0, columnspan=5, sticky="we", padx=3, pady=2)
        Tip(self.field_cb, "Pick a comparison (its threshold + operator) or an arithmetic action "
                           "(its value + op).")
        ttk.Label(ef, text="value").grid(row=1, column=0, sticky="e")
        self.val = tk.StringVar()
        self.val_ent = ttk.Entry(ef, textvariable=self.val, width=12)
        self.val_ent.grid(row=1, column=1, sticky="w")
        Tip(self.val_ent, "The new threshold / value (a number or a named constant).")
        ttk.Label(ef, text="op").grid(row=1, column=2, sticky="e", padx=(8, 0))
        self.op = tk.StringVar()
        self.op_cb = ttk.Combobox(ef, textvariable=self.op, state="readonly", width=12)
        self.op_cb.grid(row=1, column=3, sticky="w")
        Tip(self.op_cb, "The comparison or arithmetic operator.")
        ab = ttk.Button(ef, text="Apply", command=self.apply_field)
        ab.grid(row=1, column=4, padx=3)
        Tip(ab, "Apply the value / operator to the selected condition or action (in place).")
        self.op_desc = ttk.Label(ef, text="", foreground="#556", font=("Segoe UI", 8), wraplength=560)
        self.op_desc.grid(row=2, column=0, columnspan=5, sticky="w", padx=5)
        ef.columnconfigure(1, weight=1)
        # structure
        sf = ttk.LabelFrame(rf, text="Add / remove whole conditions and actions")
        sf.pack(fill="x", pady=3)
        self.struct_cb = ttk.Combobox(sf, state="readonly", width=60)
        self.struct_cb.grid(row=0, column=0, columnspan=4, sticky="we", padx=3, pady=2)
        Tip(self.struct_cb, "Pick a whole OR-slot, one expression in it, or one action, for the "
                            "Remove buttons. Add… takes text.")
        for c, (text, cmd, tip) in enumerate((
                ("Add condition…", self.add_condition, "Add terms to condition A or B from text: "
                 "`Hour >= 6 AND (12 > Hour OR FLG_RAINBOW == 1)`; prefix `B:` for condition B, "
                 "`slot=N ` to AND onto an existing OR-slot."),
                ("Remove condition", self.remove_condition, "Remove the picked OR-slot or expression."),
                ("Add action…", self.add_action, "Add one action from text: `FLG_X = 1`, `REG_Y += 2`, "
                 "`CALL EV_FOO`; prefix `alt:` for the alt stream."),
                ("Remove action", self.remove_action, "Remove the picked action."))):
            b = ttk.Button(sf, text=text, command=cmd)
            b.grid(row=1, column=c, sticky="we", padx=2, pady=2)
            Tip(b, tip)
        sf.columnconfigure(0, weight=1)
        sv = ttk.Button(rf, text="Save em.bin…", command=app.save_em)
        sv.pack(fill="x", pady=2)
        Tip(sv, "Save em.bin on its own (the main window's Save menu writes every changed file).")
        # queries
        qtab = ttk.Frame(nb)
        nb.add(qtab, text="Queries (game state)")
        qlb = tk.Listbox(qtab, font=("Consolas", 9))
        qsb = ttk.Scrollbar(qtab, command=qlb.yview)
        qlb.config(yscrollcommand=qsb.set)
        qlb.pack(side="left", fill="both", expand=True)
        qsb.pack(side="left", fill="y")
        for i, (en, jp) in enumerate(em.names.query_names):
            qlb.insert("end", f"{i:3d}  {en}" + (f"  —  {jp}" if jp else ""))
        self.shown, self.use_sites, self.fields, self.struct_items = [], [], [], []
        self._bodies = {}
        self.flt.trace_add("write", lambda *_a: self.fill())
        self.lb.bind("<<ListboxSelect>>", lambda _e: self.pick())
        self.uses.bind("<Double-Button-1>", self.jump)
        self.field_cb.bind("<<ComboboxSelected>>", lambda _e: self.on_field())
        self.op_cb.bind("<<ComboboxSelected>>", lambda _e: self.op_desc.config(text=emscript.OP_HELP.get(self.op.get(), "")))
        self.doc.subscribe(self._doc_changed)
        self.fill()

    # ---- data ------------------------------------------------------------------ #
    @property
    def em(self):
        return self.doc.em

    def _doc_changed(self, _what):
        if not self.win.winfo_exists():
            return
        sel = self.selected()
        self._bodies = {}
        self.fill()
        if sel is not None:
            self.select_idx(sel.idx)

    def bodies(self):
        if not self._bodies:
            self._bodies = {e.idx: self.em.format_entry(e).upper() for e in self.em.entries}
        return self._bodies

    def fill(self):
        em = self.em
        q = self.flt.get().upper()
        self.lb.delete(0, "end")
        self.shown = []
        bodies = self.bodies()
        for e in em.entries:
            if q and q not in bodies.get(e.idx, ""):
                continue
            marks = "".join(m for m, has in (("A", e.cond_a), ("B", e.cond_b), ("!", e.actions),
                                             ("~", e.alt_actions)) if has)
            self.lb.insert("end", f"{e.idx:3d} {marks:<4} {e.name or '(unnamed)'}")
            self.shown.append(e)
        self.win.title("Event Manager (em.bin) — %d entries" % len(em.entries))

    def selected(self):
        s = self.lb.curselection()
        return self.shown[s[0]] if (s and s[0] < len(self.shown)) else None

    def select_idx(self, idx):
        for k, e in enumerate(self.shown):
            if e.idx == idx:
                self.lb.selection_clear(0, "end")
                self.lb.selection_set(k)
                self.lb.see(k)
                self.pick()
                return True
        return False

    def pick(self):
        e = self.selected()
        em = self.em
        if e is None:
            return
        set_text(self.detail, em.format_entry(e))
        self.uses.delete(0, "end")
        self.use_sites = []
        for pos, entry, pc, st in self.app.em_uses(e.idx):
            self.uses.insert("end", "%s  scene@0x%04x  0x%04x  %s"
                             % (catalog.bank_title(self.doc.container.banks[pos])[:40], entry, pc,
                                script.opcode_mnemonic(st.op)))
            self.use_sites.append((pos, entry, pc))
        self.fields = editable_fields(em, e)
        self.field_cb.config(values=[f["label"][:70] for f in self.fields])
        if self.fields:
            self.field_cb.current(0)
            self.on_field()
        else:
            self.field_cb.set("")
            self.val.set("")
            self.op.set("")
        self.refresh_struct(e)

    def on_field(self):
        i = self.field_cb.current()
        if 0 <= i < len(self.fields):
            f = self.fields[i]
            self.val.set("" if f["val"] is None else str(f["val"]))
            self.op_cb.config(values=f["ops"])
            self.op.set(f["op"] or "")
            self.val_ent.config(state="normal" if f["has_val"] else "disabled")
            self.op_desc.config(text=emscript.OP_HELP.get(self.op.get(), ""))

    def refresh_struct(self, e):
        em = self.em
        self.struct_items = []
        labels = []
        for which, slots in (("a", e.cond_a or []), ("b", e.cond_b or [])):
            for si, exprs in enumerate(slots):
                labels.append("cond %s · slot %d  (whole OR-slot, %d expr)" % (which.upper(), si, len(exprs)))
                self.struct_items.append(("cond", which, si, None))
                for xi, x in enumerate(exprs):
                    labels.append("   cond %s · slot %d · expr %d:  %s" % (which.upper(), si, xi, x.pretty(em.names)))
                    self.struct_items.append(("cond", which, si, xi))
        for stream, acts in (("main", e.actions or []), ("alt", e.alt_actions or [])):
            for ai, act in enumerate(acts):
                labels.append("action %s · #%d:  %s" % (stream, ai, act.pretty(em.names)))
                self.struct_items.append(("act", stream, ai, None))
        self.struct_cb.config(values=labels)
        self.struct_cb.set(labels[0] if labels else "")

    def jump(self, _e=None):
        s = self.uses.curselection()
        if s:
            pos, entry, pc = self.use_sites[s[0]]
            self.app.open_scene(pos, entry, focus_pc=pc)

    # ---- edits (all through the document: undoable, tracked as unsaved) ---------- #
    def _edit(self, label, fn, reselect=None):
        try:
            with self.doc.edit(label):
                out = fn()
        except Exception as ex:  # noqa: BLE001 - report, the document already rolled back
            messagebox.showerror("Event Manager", str(ex), parent=self.win)
            return None
        if reselect is not None:
            self.select_idx(reselect)
        self.app.status(label + "  (em.bin unsaved)")
        return out if out is not None else True

    def apply_field(self):
        e = self.selected()
        i = self.field_cb.current()
        if e is None or not 0 <= i < len(self.fields):
            return None
        f = self.fields[i]
        idx, path = e.idx, f["path"]
        val = self.val.get().strip()
        op = self.op.get()

        def do():
            em = self.em
            obj, lit = _resolve(em, idx, path)
            if lit is not None and val != "":
                em.set_operand_value(lit, int(val, 0))
            if op and op != f["op"]:
                if path[0] == "cond":
                    em.set_cmp_operator(obj, op)
                else:
                    em.set_action_op(obj, op)
        return self._edit("Edit em.bin entry %d" % idx, do, reselect=idx)

    def add_entry(self):
        src = self.selected()
        clone = None
        if src is not None and messagebox.askyesno(
                "Add entry", "Copy entry %d %s (its conditions + actions) into the new entry?\n"
                             "No = an empty entry." % (src.idx, src.name or ""), parent=self.win):
            clone = src.idx
        name = simpledialog.askstring("Add entry", "Name for the new entry (in memory only: "
                                                   "emdeb.bin is not rewritten). Blank for none.",
                                      parent=self.win)
        if name is None:
            return None
        box = {}
        if self._edit("Add em.bin entry", lambda: box.update(i=self.em.add_entry(clone=clone, name=name.strip()))) is None:
            return None
        self.flt.set("")
        self.fill()
        self.select_idx(box["i"])
        return box["i"]

    def remove_entry(self):
        e = self.selected()
        if e is None:
            messagebox.showinfo("Remove entry", "Select an entry first.", parent=self.win)
            return None
        if not messagebox.askyesno(
                "Remove entry", "Delete entry %d %s? Every later entry moves down one id (internal "
                "references are renumbered; rf3.mc bridge ops are NOT)." % (e.idx, e.name or "(unnamed)"),
                parent=self.win):
            return None
        idx = e.idx
        try:
            with self.doc.edit("Remove em.bin entry %d" % idx):
                self.em.delete_entry(idx)
            how = "deleted"
        except ValueError as ex:                   # referenced by other entries
            if not messagebox.askyesno("Remove entry", "%s\n\nClear it in place instead? (ids stay "
                                       "stable; the entry evaluates FALSE and does nothing)" % ex,
                                       parent=self.win):
                return None
            if self._edit("Clear em.bin entry %d" % idx, lambda: self.em.clear_entry(idx)) is None:
                return None
            how = "cleared"
        except Exception as ex:  # noqa: BLE001
            messagebox.showerror("Remove entry", str(ex), parent=self.win)
            return None
        self.app.status("em.bin: entry %d %s (unsaved)" % (idx, how))
        return how

    def _struct_sel(self):
        i = self.struct_cb.current()
        return self.struct_items[i] if 0 <= i < len(self.struct_items) else None

    def add_condition(self):
        e = self.selected()
        if e is None:
            messagebox.showinfo("Add condition", "Select an entry first.", parent=self.win)
            return None
        spec = self.app.ask_spec("Add condition", "Condition terms for entry %d %s.\n"
                                 % (e.idx, e.name or "") + catalog.EM_CONDITION_SYNTAX_HELP,
                                 lambda t: parse_condition(self.em, self.em.entries[e.idx], t))
        if not spec:
            return None
        idx = e.idx
        box = {}

        def do():
            which, slot, exprs = parse_condition(self.em, self.em.entries[idx], spec)
            box["slot"] = self.em.add_condition(idx, which, exprs, slot=slot)
        if self._edit("Add condition to em.bin entry %d" % idx, do, reselect=idx) is None:
            return None
        return box["slot"]

    def remove_condition(self):
        sel, e = self._struct_sel(), self.selected()
        if e is None or sel is None or sel[0] != "cond":
            messagebox.showinfo("Remove condition", "Pick a condition slot or expression first.", parent=self.win)
            return None
        _k, which, slot, expr = sel
        idx = e.idx
        return self._edit("Remove condition from em.bin entry %d" % idx,
                          lambda: self.em.remove_condition(idx, which, slot, expr), reselect=idx)

    def add_action(self):
        e = self.selected()
        if e is None:
            messagebox.showinfo("Add action", "Select an entry first.", parent=self.win)
            return None
        spec = self.app.ask_spec("Add action", "Action for entry %d %s.\n" % (e.idx, e.name or "")
                                 + catalog.EM_ACTION_SYNTAX_HELP, lambda t: parse_action(self.em, t))
        if not spec:
            return None
        idx = e.idx
        box = {}

        def do():
            stream, action = parse_action(self.em, spec)
            self.em.add_action(idx, stream, action)
            box["stream"] = stream
        if self._edit("Add action to em.bin entry %d" % idx, do, reselect=idx) is None:
            return None
        return box["stream"]

    def remove_action(self):
        sel, e = self._struct_sel(), self.selected()
        if e is None or sel is None or sel[0] != "act":
            messagebox.showinfo("Remove action", "Pick an action first.", parent=self.win)
            return None
        _k, stream, index, _x = sel
        idx = e.idx
        return self._edit("Remove action from em.bin entry %d" % idx,
                          lambda: self.em.remove_action(idx, stream, index), reselect=idx)

