"""The cutscene editor's Reference window and Instruction picker.

Reference (toolbar "Reference"): searchable lists of what a scene can name --
  * Flags & variables: emdeb.bin's FLG_ / REG_ / EV_ variables (name, bit id, width, value
    range, Japanese label) and the recovered zone-2 bits (emflags.ZONE2_BLOCKS);
  * Functions: the instructions a person has verified in game (opcode_table.json
    `human_verified`), with everything the table knows about each;
  * Characters, Maps, Items: the ids and the listing form an argument takes.

Instruction picker (the Script view's right-click menu, the Insert key): every instruction by
category, a form with one
field per argument (character / map / item / flag / enum pickers where the table knows the
type), a live listing preview that can also be edited by hand, and Insert before / after the
selected statement. The preview is plain listing text, so everything goes through the same
assembler as the Source tab.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from guiutil import FilterCombo, Tip, later
from guiutil import err_text
import guiutil
from rf4s_modkit import opcode_meta as meta
from rf4s_modkit import script, scriptasm

PLACEHOLDER = ("(unbound)", "(unused)", "nop", "invalid")
CONTROL_GROUP = "Flow & dialogue (control)"
CONTROL_ORDER = ("DIALOG", "EVAL", "BR_Z", "BR_NZ", "JMP", "CALL", "RET", "RET_NZ", "PROMPT_CHOICE",
                 "PROMPT_CHOICE_FORCED", "SWITCH", "SWITCH_CLAMP", "JMP_RAND", "JMP_WEIGHTED", "FRAME")
CONTROL_HELP = {
    "DIALOG": "Show one line of dialogue (spoken by the last SetSpeaker before it). Pick an "
              "existing line, or use 'New line…' to write a new one.",
    "EVAL": "Set a flag / register: `VAR = value`, or change it (`+=`, `-=`, …).",
    "BR_Z": "Jump to the target when the condition is FALSE (skip the next part unless …).",
    "BR_NZ": "Jump to the target when the condition is TRUE.",
    "JMP": "Always continue at the target.",
    "CALL": "Run the code at the target as a subroutine; its RET comes back here.",
    "RET": "End the scene (or return from a CALL).",
    "RET_NZ": "End the scene (or return from a CALL) when the condition is TRUE.",
    "PROMPT_CHOICE": "A choice menu: each option is a dialogue line and where it goes. Cancel "
                     "(B button) moves the cursor to the last option, so the last option "
                     "doubles as the cancel answer.",
    "PROMPT_CHOICE_FORCED": "A choice menu that cannot be cancelled.",
    "SWITCH": "Jump to target number N, where N is the selector's value (0 = the first).",
    "SWITCH_CLAMP": "Like SWITCH, but values past the end use the last target.",
    "JMP_RAND": "Jump to one of the targets at random.",
    "JMP_WEIGHTED": "Jump to one of the targets at random, each with its own weight.",
    "FRAME": "Reserve N stack words for the scene or subroutine. Not needed by hand: the "
             "editor adds or raises it by itself when an argument is a nested expression "
             "(e.g. reg0 + 1) evaluated while other arguments are on the stack.",
}


# ---- data ------------------------------------------------------------------------------ #
_CACHE = {}


_NAME_KEYS = ("chars", "maps", "items")        # built from the game's names (gamenames)


def _cached(key, fn):
    if key in _NAME_KEYS:                       # a saved name file / 00_mods change rebuilds them
        from rf4s_modkit import gamenames
        gen = gamenames.generation()
        if _CACHE.get("_names_gen") != gen:
            for k in _NAME_KEYS:
                _CACHE.pop(k, None)
            _CACHE["_names_gen"] = gen
    if key not in _CACHE:
        try:
            _CACHE[key] = fn()
        except Exception:  # noqa: BLE001 -- a missing table just leaves the list empty
            _CACHE[key] = []
    return _CACHE[key]


def character_choices():
    """[(display, listing token)] for every character id, e.g. ('Forte  (4)', 'actor(Forte)')."""
    def build():
        names, _u = script._actor_tables()
        return [("%s  (%d)" % (names[i], i), script.actor_leaf_text(i)) for i in sorted(names)]
    return _cached("chars", build)


def map_choices():
    def build():
        from rf4s_modkit import map_names
        out = []
        for i in range(map_names.map_count()):
            f = map_names.map_file(i)
            if f:
                nm = map_names.map_name(i) or ""
                out.append(("%s  %s  (%d)" % (f, nm, i), script.map_leaf_text(i)))
        return out
    return _cached("maps", build)


def item_choices():
    def build():
        from rf4s_modkit import gamenames
        d = gamenames.table("items")
        return [("%s  (%d)" % (v, k), str(k)) for k, v in sorted(d.items()) if v]
    return _cached("items", build)


def flag_rows(doc):
    """[(name, kind, id text, width, values, description, token)] -- emdeb's variables, then
    the recovered zone-2 bits."""
    from rf4s_modkit import emflags
    tbl = getattr(doc, "emf_vars", None)
    if tbl is None:
        tbl = _cached("emf", emflags.EmFlagTable.load)
    rows = []
    for v in getattr(tbl, "variables", []):
        w = v.bit_width
        rng = "0 / 1" if w == 1 else "0 – %d" % ((1 << w) - 1)
        kind = {"FLG": "flag", "REG": "value", "EV": "event"}.get(v.kind, v.kind or "")
        desc = (v.jp_name or "") + ("  (your variable)" if v.extra else "")
        rows.append((v.name, kind, str(v.bit_offset), str(w), rng, desc, v.name))
    for lo, hi, name, detail in emflags.ZONE2_BLOCKS:
        ids = str(emflags.ZONE2_BASE + lo) if lo == hi else "%d – %d" % (emflags.ZONE2_BASE + lo, emflags.ZONE2_BASE + hi)
        rows.append(("zone 2: " + name, "zone-2 bit", ids, "1", "0 / 1",
                     detail + "  (ops 318 / 443 / 445 and map objects, not an EVAL variable)",
                     "flag@%d/1" % (emflags.ZONE2_BASE + lo)))
    return rows


def variable_choices(doc):
    """[(display, token)] for EVAL / condition pickers: the emdeb variables and the registers."""
    out = [("reg%d  (VM register)" % i, "reg%d" % i) for i in range(10)]
    for name, kind, bid, w, rng, desc, tok in flag_rows(doc):
        if kind != "zone-2 bit":
            out.append(("%s  %s" % (name, desc[:40]), tok))
    return out


def verified_ops():
    """Action ops and control mnemonics marked human-verified in opcode_table.json."""
    acts = [int(k) for k, r in meta.TABLE["actions"].items() if r.get("human_verified")]
    ctl = [r["mnemonic"] for r in meta.TABLE["control"].values() if r.get("human_verified")]
    return sorted(acts), ctl


def op_info_text(op):
    """Everything opcode_table.json knows about an action op, as plain text."""
    r = meta.table_row(op) or {}
    L = [meta.prototype(op), ""]
    fam = meta.OPCODE_ARGS.get(op)
    if fam:
        L.append("opcode 0x%03X = %s" % (op, ", ".join("%s %s" % (a["name"], a["value"]) for a in fam)))
    L.append("category: %s    opcode: 0x%03X    %s" % (
        meta.category_label(op), op, "✓ verified in game" if r.get("human_verified") else "not yet verified in game"))
    L += ["", meta.describe(op) or ""]
    args = r.get("args") or []
    if fam or args:
        L += ["", "Arguments:"]
        for a in fam or ():
            L.append("  %s (in the opcode): %s" % (a["name"], a["values"]))
        for i, a in enumerate(args):
            L.append("  %d. %s — %s%s   [%s]" % (i, a["name"], a.get("type") or "",
                                               (": " + a["values"]) if a.get("values") else "",
                                               "✓ verified" if a.get("human_verified") else "not verified"))
            for v, e in (a.get("value_names") or {}).items():
                L.append("       %s = %s%s%s" % (v, e["name"], ("  " + e["text"]) if e.get("text") else "",
                                                 "  ✓" if e.get("human_verified") else "  (untested)"))
            for te in a.get("tests") or ():
                L.append("       tested %s: %s -> %s" % (te["date"], te["call"], te["observed"]))
    for k, lab in (("returns", "Returns"), ("blocking", "Blocks"), ("side_effects", "Side effects")):
        if r.get(k):
            L += ["", "%s: %s" % (lab, r[k])]
    ex = r.get("example")
    if ex:
        L += ["", "Example (bank %d):" % ex["bank"]] + ex["lines"]
    return "\n".join(L)


def control_info_text(mnem):
    r = next((x for x in meta.TABLE["control"].values() if x["mnemonic"] == mnem), {})
    L = [r.get("prototype") or mnem, "", CONTROL_HELP.get(mnem, ""), "", r.get("description") or ""]
    ex = r.get("example")
    if ex:
        L += ["", "Example (bank %d):" % ex["bank"]] + ex["lines"]
    return "\n".join(L)


# ---- widgets --------------------------------------------------------------------------- #
def _sort_key(v):
    """Sort key for a list cell: numbers (decimal or 0x hex) by value and before text, the
    rest case-insensitively."""
    s = str(v).strip()
    try:
        return (0, int(s, 0), "")
    except ValueError:
        return (1, 0, s.lower())


class _Filtered(ttk.Frame):
    """A filter box over a Treeview: every typed word must appear in the row. A click on a
    column heading sorts by that column (again: the other way round)."""

    def __init__(self, parent, columns, widths, rows, on_select=None, on_activate=None, height=18,
                 sort_by=None):
        super().__init__(parent)
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 4))
        ttk.Label(top, text="Filter").pack(side="left")
        self.q = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.q)
        e.pack(side="left", fill="x", expand=True, padx=4)
        self.count = ttk.Label(top, foreground="#888")
        self.count.pack(side="right")
        self.export_btn = ttk.Button(top, text="Export CSV…", command=self.export_csv)
        Tip(self.export_btn, "Save the rows shown (filtered and in this order) as a CSV file.")
        self._export_shown = False
        f = ttk.Frame(self)
        f.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(f, columns=columns, show="headings", height=height)
        self._columns = list(columns)
        self._sort = (self._columns.index(sort_by), False) if sort_by in self._columns else None
        for c, w in zip(columns, widths):
            self.tree.heading(c, text=c, command=lambda c=c: self.sort_by(c))
            self.tree.column(c, width=w, stretch=(w >= 200), anchor="w")
        self._label_headings()
        sb = ttk.Scrollbar(f, command=self.tree.yview)
        self.tree.config(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.rows = rows
        self._pending = None
        self.q.trace_add("write", lambda *_a: self._schedule())
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", lambda _e: on_select(self.selected()))
        if on_activate:
            self.tree.bind("<Double-Button-1>", lambda _e: on_activate(self.selected()))
            self.tree.bind("<Return>", lambda _e: on_activate(self.selected()))
        self.entry = e
        self.fill()

    def _label_headings(self):
        for i, c in enumerate(self._columns):
            mark = ""
            if self._sort is not None and self._sort[0] == i:
                mark = "  ▼" if self._sort[1] else "  ▲"
            self.tree.heading(c, text=c + mark)

    def sort_by(self, column, reverse=None):
        """Sort the list by `column` (a click on its heading; a second click reverses it)."""
        i = self._columns.index(column)
        if reverse is None:
            reverse = bool(self._sort and self._sort[0] == i and not self._sort[1])
        self._sort = (i, reverse)
        self._label_headings()
        self.fill()

    def show_export(self, on):
        """Show / hide the Export CSV button (Options -> Advanced)."""
        on = bool(on)
        if on == self._export_shown:
            return
        if on:
            self.export_btn.pack(side="right", padx=(0, 6), before=self.count)
        else:
            self.export_btn.pack_forget()
        self._export_shown = on

    def _matching(self):
        """Row indexes that pass the filter, in the current sort order (no display cap)."""
        words = self.q.get().lower().split()
        out = []
        for i in self._order():
            if words:
                low = " ".join(str(x) for x in self.rows[i]).lower()
                if not all(w in low for w in words):
                    continue
            out.append(i)
        return out

    def shown_rows(self):
        """The visible columns of every row the filter lets through, in the list's order
        (all of them, also past the display cap)."""
        n = len(self._columns)
        return [["" if v is None else str(v) for v in self.rows[i][:n]] for i in self._matching()]

    def write_csv(self, path):
        import csv
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:     # BOM: Excel reads UTF-8
            w = csv.writer(fh)
            w.writerow(self._columns)
            w.writerows(self.shown_rows())

    def export_csv(self):
        from tkinter import filedialog, messagebox
        rows = self.shown_rows()
        if not rows:
            return
        f = filedialog.asksaveasfilename(parent=self, title="Export list as CSV", defaultextension=".csv",
                                         filetypes=[("CSV", "*.csv"), ("All", "*.*")])
        if not f:
            return
        try:
            self.write_csv(f)
        except OSError as e:
            messagebox.showerror("Export CSV", str(e), parent=self)

    def set_rows(self, rows):
        """Replace the rows (keeps the filter text and the sort)."""
        self.rows = rows
        self.fill()

    def _order(self):
        idx = list(range(len(self.rows)))
        if self._sort is not None:
            col, rev = self._sort
            idx.sort(key=lambda k: _sort_key(self.rows[k][col] if col < len(self.rows[k]) else ""),
                     reverse=rev)
        return idx

    def _schedule(self):
        if self._pending is not None:
            self.after_cancel(self._pending)
        self._pending = later(self, self.fill, 150)

    def fill(self):
        if self._pending is not None:       # a direct refill makes the scheduled one moot (it
            try:                            # would wipe a selection made right after this)
                self.after_cancel(self._pending)
            except tk.TclError:
                pass
        self._pending = None
        self.tree.delete(*self.tree.get_children())
        n = 0
        cap = guiutil.list_rows()           # once: it reads the settings file
        for i in self._matching():
            shown = self.rows[i][:len(self.tree["columns"])]
            self.tree.insert("", "end", iid=str(i), values=shown)
            n += 1
            if n >= cap:
                break
        self.count.config(text="%d shown%s" % (n, " (first %d)" % cap if n >= cap else ""))

    def selected(self):
        s = self.tree.selection()
        return self.rows[int(s[0])] if s else None


class ReferenceWindow:
    """Searchable reference lists (one window per editor)."""

    TABS = ("Flags & variables", "Functions", "Text codes", "Characters", "Maps", "Items", "Trigger types")

    STEP_MS = 30                # hidden build: the pause between tabs, so the editor stays responsive

    def __init__(self, app, hidden=False):
        """`hidden`: preloaded by the editor -- the window starts withdrawn and its tabs are
        built one per idle step (show() finishes any still to build)."""
        self.app = app
        self.win = tk.Toplevel(app.frame)
        if hidden:
            self.win.withdraw()
        self.win.title("Cutscene Editor — Reference")
        self.win.geometry("1000x640")
        self.nb = ttk.Notebook(self.win)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.status = ttk.Label(self.win, foreground="#888")
        self.status.pack(fill="x", padx=8, pady=(0, 6))
        self._steps = [
            self._flags, self._functions, self._text_codes,
            lambda: self._simple("Characters", ("character", "use as"), (420, 300), character_choices(),
                                 "Character ids: arguments typed 'char id' take actor(Name) (or the number)."),
            lambda: self._simple("Maps", ("map", "use as"), (520, 300), map_choices(),
                                 "Map ids: arguments typed 'map id' take map(MAP_FILE) (or the number)."),
            lambda: self._simple("Items", ("item", "use as"), (520, 120), item_choices(),
                                 "Item ids: arguments typed 'item id' take the number."),
            self._action_types, self.apply_list_settings]
        self._step_job = None
        self._uses_stale = False
        if hidden:
            self._step_job = later(self.win, self._next_step, self.STEP_MS)
        else:
            self._finish_build()

    @property
    def built(self):
        return not self._steps

    def _next_step(self):
        self._step_job = None
        try:
            if not self.win.winfo_exists() or not self._steps:
                return
        except tk.TclError:
            return
        self._steps.pop(0)()
        if self._steps:
            self._step_job = later(self.win, self._next_step, self.STEP_MS)

    def _finish_build(self):
        if self._step_job is not None:
            try:
                self.win.after_cancel(self._step_job)
            except tk.TclError:
                pass
            self._step_job = None
        while self._steps:
            self._steps.pop(0)()

    def lists(self):
        """Every filterable list in the window."""
        out, todo = [], [self.win]
        while todo:
            w = todo.pop()
            if isinstance(w, _Filtered):
                out.append(w)
            todo.extend(w.winfo_children())
        return out

    def apply_list_settings(self):
        """Follow Options -> Advanced: the Export CSV buttons."""
        on = bool(getattr(type(self.app), "reference_csv_setting", lambda: False)())
        for lst in self.lists():
            lst.show_export(on)

    def show(self, tab=None):
        self._finish_build()                # opened while the preload was still building
        self.win.deiconify()
        if self._uses_stale:                # edits made while it was hidden
            self._uses_stale = False
            self.refresh_uses()
        self.win.lift()
        if tab in self.TABS:
            self.nb.select(self.TABS.index(tab))

    def copy(self, text, what=""):
        if not text:
            return
        self.win.clipboard_clear()
        self.win.clipboard_append(text)
        self.status.config(text="copied %s%s" % (text, ("  (" + what + ")") if what else ""))

    def _flags(self):
        f = ttk.Frame(self.nb, padding=6)
        self.nb.add(f, text=self.TABS[0])
        ttk.Label(f, foreground="#666", wraplength=940, justify="left", text=(
            "emdeb.bin's variables: FLG_ = a 1-bit flag, REG_ = a number, EV_ = an event slot. "
            "id = the bit offset in the game-flags store, width = bits. Use the name in a "
            "condition or EVAL: BR_Z (FLG_X == 1) -> …, EVAL (REG_Y = 3). Zone-2 rows are the "
            "recovered bits past emdeb's names. reads / writes = how many statements of every "
            "bank and em.bin entries use it (unsaved edits included); select a variable to list "
            "them below, double-click a use to open it. Double-click a variable = copy its "
            "name.")).pack(anchor="w", pady=(0, 4))
        self._flag_base = flag_rows(self.app.doc)
        pw = ttk.PanedWindow(f, orient="vertical")
        pw.pack(fill="both", expand=True)
        top, bot = ttk.Frame(pw), ttk.Frame(pw)
        pw.add(top, weight=3)
        pw.add(bot, weight=2)
        self.flag_list = t = _Filtered(top, ("name", "kind", "id", "width", "reads", "writes", "description"),
                                       (250, 60, 80, 45, 55, 55, 360), self._flag_rows(None),
                                       on_select=self._show_var_uses,
                                       on_activate=lambda r: r and self.copy(r[7], r[0]), height=12)
        t.pack(fill="both", expand=True)
        self.uses_hdr = ttk.Label(bot, text="Used by: select a variable", font=("Segoe UI", 9, "bold"))
        self.uses_hdr.pack(anchor="w", pady=(4, 2))
        uf = ttk.Frame(bot)
        uf.pack(fill="both", expand=True)
        self.uses = ttk.Treeview(uf, columns=("where", "pc", "access", "statement"), show="headings", height=8)
        for c, w in (("where", 330), ("pc", 60), ("access", 80), ("statement", 460)):
            self.uses.heading(c, text=c)
            self.uses.column(c, width=w, stretch=c in ("where", "statement"), anchor="w")
        sb = ttk.Scrollbar(uf, command=self.uses.yview)
        self.uses.config(yscrollcommand=sb.set)
        self.uses.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.uses.bind("<Double-Button-1>", lambda _e: self._open_use())
        self.uses.bind("<Return>", lambda _e: self._open_use())
        Tip(self.uses, "Every statement (in any bank) and em.bin entry that reads or writes the "
                       "selected variable. Double-click: open it.")
        self._use_rows = {}
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(4, 0))
        ttk.Button(b, text="Copy name", command=lambda: t.selected() and self.copy(t.selected()[7])).pack(side="left")
        self._counting = False               # the reads / writes counts start when this tab shows
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self._flags_tab_shown(), add="+")

    def _flags_tab_shown(self):
        try:
            current = self.nb.tab(self.nb.select(), "text")
        except tk.TclError:
            return
        if current == self.TABS[0] and not self._counting:
            self._counting = True
            self._count_uses()

    def _flag_rows(self, index):
        """The list rows: (name, kind, id, width, reads, writes, description, token, key).
        key = (bit offset, width) of an emdeb variable (None for the zone-2 rows)."""
        rows = []
        for name, kind, bid, w, _rng, desc, tok in self._flag_base:
            key = (int(bid), int(w)) if kind != "zone-2 bit" else None
            if key is None:
                r = w_ = "—"
            elif index is None:
                r = w_ = "…"
            else:
                u = index.get(key, ())
                r = sum(1 for x in u if x[-2 if x[0] == "script" else 3] != "write") if u else 0
                w_ = sum(1 for x in u if x[-2 if x[0] == "script" else 3] != "read") if u else 0
            rows.append((name, kind, bid, w, r, w_, desc, tok, key))
        return rows

    def _count_uses(self):
        """Fill the reads / writes columns. The first time scans every bank (seconds), on a
        worker thread (app.var_index_async), so the window stays usable meanwhile."""
        if not self.win.winfo_exists() or self.app.doc.container is None:
            return
        if self.app._var_uses is None:
            self.status.config(text="counting variable uses in every bank…")
        self.app.var_index_async(self._apply_counts)

    def _apply_counts(self, idx, err):
        if not self.win.winfo_exists():
            return
        if err is not None or idx is None:  # a display aid: leave the counts blank
            self.status.config(text="could not count uses: %s" % (err_text(err) if err else "no index"))
            return
        t = self.flag_list
        sel = t.selected()
        t.rows = self._flag_rows(idx)
        t.fill()
        if sel is not None:                 # a refill keeps the selected variable selected
            for iid in t.tree.get_children():
                if t.rows[int(iid)][0] == sel[0]:
                    t.tree.selection_set(iid)
                    t.tree.see(iid)
                    break
        self.status.config(text="")

    def refresh_uses(self):
        """After an edit: recount (the selection, and with it the 'Used by' list, follows).
        Hidden (preloaded, or closed) or still building: recounted when shown."""
        if not self.win.winfo_exists():
            return
        if not self.built or self.win.state() == "withdrawn":
            self._uses_stale = True
            return
        if self._counting:
            self._count_uses()

    @staticmethod
    def _stmt_text(bank, st):
        if st.op < 0xFFF0:
            args = script.stmt_arg_strs(bank.data, st)
            return script.render_action(st.op, args) or "%s(%s)" % (script.opcode_mnemonic(st.op), ", ".join(args))
        ex = [script.disasm_expr(bank.data, e)[0] for e in (getattr(st, "expr_refs", None) or []) if e is not None]
        return st.mnem + ((" (" + ", ".join(ex) + ")") if ex else "")

    def _show_var_uses(self, r):
        from . import catalog
        u = self.uses
        u.delete(*u.get_children())
        self._use_rows = {}
        if not r or r[8] is None:
            self.uses_hdr.config(text="Used by: (zone-2 bits are listed in the map editor's flag "
                                      "reference)" if r else "Used by: select a variable")
            return
        if self.app._var_uses is None:           # still counting: fill in when it is done
            self.uses_hdr.config(text="Used by: %s — counting uses in every bank…" % r[0])
            self.app.var_index_async(lambda _i, _e: self.win.winfo_exists() and self._show_var_uses(r)
                                     if self.flag_list.selected() == r else None)
            return
        uses = self.app.var_uses(*r[8])
        c, em = self.app.doc.container, self.app.doc.em
        n = 0
        for x in uses:
            if x[0] == "script":
                _k, pos, entry, pc, acc, st = x
                bank = c.banks[pos]
                vals = ("%s · scene @%04x" % (catalog.bank_title(bank), entry), "%04x" % pc, acc,
                        self._stmt_text(bank, st))
            else:
                _k, idx, where, acc = x
                nm = em.entries[idx].name if em is not None and 0 <= idx < len(em.entries) else ""
                vals = ("em.bin #%d %s" % (idx, nm or ""), "", acc, where)
            iid = "u%d" % n
            u.insert("", "end", iid=iid, values=vals)
            self._use_rows[iid] = x
            n += 1
        nb = len({(x[1], x[2]) for x in uses if x[0] == "script"})
        self.uses_hdr.config(text="Used by: %s — %d use%s in %d scene%s%s" % (
            r[0], n, "" if n == 1 else "s", nb, "" if nb == 1 else "s",
            ", %d in em.bin" % sum(1 for x in uses if x[0] == "em") if any(x[0] == "em" for x in uses) else ""))

    def _open_use(self):
        s = self.uses.selection()
        x = self._use_rows.get(s[0]) if s else None
        if x is None:
            return
        if x[0] == "script":
            _k, pos, entry, pc, _acc, _st = x
            self.app.open_scene(pos, entry, focus_pc=pc)
            try:
                self.app.frame.winfo_toplevel().lift()
            except tk.TclError:
                pass
        else:
            w = self.app.open_event_manager()
            if w is not None:
                w.open_entry(x[1])

    def show_var(self, name):
        """Select variable `name` in the Flags tab (the script view's 'Uses of …')."""
        self.show(self.TABS[0])
        t = self.flag_list
        t.q.set(name)
        t.fill()
        for iid in t.tree.get_children():
            if t.rows[int(iid)][0] == name:
                t.tree.selection_set(iid)
                t.tree.see(iid)
                self._show_var_uses(t.rows[int(iid)])
                return True
        return False

    def _function_rows(self):
        """(rows, intro text) for the Functions tab: the verified instructions, or every one
        when Options -> Advanced -> 'Show unverified instructions in the Reference' is on."""
        acts, ctl = verified_ops()
        show_all = bool(getattr(type(self.app), "reference_unverified_setting", lambda: False)())
        done = set(acts)
        ops = sorted(int(k) for k in meta.TABLE["actions"]) if show_all else acts
        rows = []
        for r in meta.TABLE["control"].values():
            if show_all or r.get("human_verified"):
                m = r["mnemonic"]
                rows.append((m, r.get("op_hex", ""), "✓" if r.get("human_verified") else "",
                             CONTROL_HELP.get(m, ""), ("ctl", m)))
        for op in ops:
            rows.append((meta.prototype(op), "0x%03X" % op, "✓" if op in done else "",
                         meta.describe(op) or "", ("op", op)))
        n = len(acts) + len(ctl)
        if show_all:
            text = ("Every instruction (%d); the %d with a ✓ were checked in game by a person. "
                    "Only the checked ones: untick 'Show unverified instructions in the Reference' "
                    "(Options -> Advanced)." % (len(rows), n))
        else:
            text = ("Instructions a person has checked in game (%d so far). Mark more with "
                    "\"human_verified\": true in refdata/opcode_table.json. To list every "
                    "instruction here, tick 'Show unverified instructions in the Reference' "
                    "(Options -> Advanced); every one is also in the Instruction picker." % n)
        return rows, text

    def refresh_functions(self):
        """Rebuild the Functions list (after the Advanced setting changed)."""
        rows, text = self._function_rows()
        self._fn_intro.config(text=text)
        self._fn_list.set_rows(rows)

    def _functions(self):
        f = ttk.Frame(self.nb, padding=6)
        self.nb.add(f, text=self.TABS[1])
        rows, text = self._function_rows()
        self._fn_intro = ttk.Label(f, foreground="#666", wraplength=940, justify="left", text=text)
        self._fn_intro.pack(anchor="w", pady=(0, 4))
        pw = ttk.PanedWindow(f, orient="vertical")
        pw.pack(fill="both", expand=True)
        top = ttk.Frame(pw)
        det = tk.Text(pw, height=12, wrap="word", font=("Consolas", 9))
        t = _Filtered(top, ("Function", "Opcode", "✓", "Description"), (360, 90, 30, 450), rows,
                      on_select=lambda r: self._show_fn(det, r),
                      on_activate=lambda r: r and self.app.ask_insert_instruction(preset=r[4]), height=10,
                      sort_by="Opcode")
        t.pack(fill="both", expand=True)
        self._fn_list = t
        pw.add(top, weight=1)
        pw.add(det, weight=1)
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(4, 0))
        ttk.Button(b, text="Insert this instruction…",
                   command=lambda: t.selected() and self.app.ask_insert_instruction(preset=t.selected()[4])).pack(side="left")

    def _text_codes(self):
        """The codes a dialogue line can contain (textlint.token_reference)."""
        from rf4s_modkit import textlint
        f = ttk.Frame(self.nb, padding=6)
        self.nb.add(f, text="Text codes")
        ttk.Label(f, foreground="#666", wraplength=940, justify="left", text=(
            "Codes inside dialogue text. The game swaps a ＠…＠ code for a value when it shows the "
            "line. Text can't read the script's registers, so a code reads a text slot instead: "
            "a small table per kind of value (numbers, characters, items, places …), 32 slots "
            "each. The script fills slot n before the line, e.g. SetVar3(0, reg0) and then "
            "\"Gained ＠０＠G!\" shows the number in number slot 0. The \"filled by\" column "
            "names the instructions that write the slot; a slot keeps its value until something "
            "writes it again. <n> is one character: 0-9 or ０-９, then Ａ-Ｖ = 10-31. "
            "Colours, raise / lower and button icons can't be typed: the editors write them as "
            "backslash escapes (\\red, \\btn(a) ...), a real backslash as \\\\. "
            "Double-click = copy the code.")).pack(anchor="w", pady=(0, 4))
        rows = [(code, group, shows, setby or "—", code.replace("<n>", "０"))
                for code, group, shows, setby, _k in textlint.token_reference()]
        t = _Filtered(f, ("code", "group", "shows", "filled by"), (200, 90, 520, 150), rows,
                      on_activate=lambda r: r and self.copy(r[4], r[0]))
        t.pack(fill="both", expand=True)
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(4, 0))
        ttk.Button(b, text="Copy code", command=lambda: t.selected() and self.copy(t.selected()[4])).pack(side="left")

    _PICK = {"first": "the first matching trigger, in list order",
             "last": "only the LAST trigger runs (a new trigger shadows the ones before it)",
             "all": "every matching trigger is collected and runs",
             "first_exact_else_last_wildcard": "an exact key match first, else the last -1 (wildcard) trigger",
             "unknown": "unknown (no reader found)"}

    def _action_types(self):
        """Every trigger type (rf4s_modkit.entry_types): what makes a scene of it run."""
        from rf4s_modkit import entry_types as et
        f = ttk.Frame(self.nb, padding=6)
        self.nb.add(f, text="Trigger types")
        ttk.Label(f, foreground="#666", wraplength=940, justify="left", text=(
            "A trigger type is WHEN a scene runs. Every bank starts with a table of 74 slots, one "
            "per trigger type; a slot lists that type's triggers: {scene pc, keys}. Each situation in the "
            "game (entering a map, talking to an NPC, interacting with an event actor, a warp "
            "landing, a gift...) has its type number built in: the game loads the bank that fits "
            "the situation (the map's bank, the NPC's bank, the town event's or story chapter's "
            "bank), walks that type's triggers, compares their keys with what is happening (a map "
            "id, an event-actor key, a warp number, an item, a talk-line index...; -1 is usually a "
            "wildcard) and runs the winner's scene. Conditions such as a story flag are mostly not "
            "in the trigger: the scene tests them itself at its start (the Event Manager guard). "
            "So a scene's trigger is bank + type + keys - the Triggers tab edits them. "
            "Double-click a type = show only its scenes in the Banks list.")).pack(anchor="w", pady=(0, 4))
        rows = []
        for t in sorted(et.ENTRY_TYPES):
            sp = et.ENTRY_TYPES[t]
            n = (et.CORPUS_STATS.get(t) or {}).get("entries", 0)
            keys = ", ".join("%s %s" % (k["index"], k["name"]) for k in sp.get("keys") or []) or "-"
            rows.append((t, sp["name"], n if n else "code only", keys, sp.get("summary", ""), t))
        pw = ttk.PanedWindow(f, orient="vertical")
        pw.pack(fill="both", expand=True)
        top = ttk.Frame(pw)
        det = tk.Text(pw, height=12, wrap="word", font=("Segoe UI", 9))
        tab = _Filtered(top, ("type", "name", "triggers", "keys", "runs when"), (50, 190, 70, 190, 460),
                        rows, on_select=lambda r: self._show_type(det, r),
                        on_activate=lambda r: r and self._filter_banks(r[5]), height=12)
        tab.pack(fill="both", expand=True)
        pw.add(top, weight=1)
        pw.add(det, weight=1)
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(4, 0))
        ttk.Button(b, text="Show its scenes in the Banks list",
                   command=lambda: tab.selected() and self._filter_banks(tab.selected()[5])).pack(side="left")

    def _show_type(self, det, r):
        from rf4s_modkit import entry_types as et
        det.config(state="normal")
        det.delete("1.0", "end")
        if r:
            t = r[5]
            sp = et.ENTRY_TYPES[t]
            lines = ["type %d  %s" % (t, sp["name"]), "", sp.get("summary", "")]
            if sp.get("bank"):
                lines += ["", "Bank: " + sp["bank"]]
            ks = sp.get("keys") or []
            lines += ["", "Keys:" if ks else "Keys: none"]
            for k in ks:
                lines.append("  %s  %s: %s%s" % (k["index"], k["name"], k.get("meaning", ""),
                                                 "  (-1 = any)" if k.get("wildcard") else ""))
            lines += ["", "Which trigger runs: " + self._PICK.get(sp.get("select"), sp.get("select") or "?")]
            st = et.CORPUS_STATS.get(t)
            if st:
                lines.append("In the shipped file: %d triggers in %s banks" % (
                    st["entries"], ", ".join("%d %s" % (v, k) for k, v in st["banks"].items())))
            else:
                lines.append("In the shipped file: none (the game's code knows this type, no scene uses it)")
            if sp.get("confidence"):
                lines.append("Confidence: " + sp["confidence"])
            if sp.get("matcher"):
                lines.append("Matcher: " + sp["matcher"])
            if sp.get("notes"):
                lines += ["", sp["notes"]]
            det.insert("1.0", "\n".join(lines))
        det.config(state="disabled")

    def _filter_banks(self, t):
        """Point the Banks list's Trigger filter at type `t`."""
        br = getattr(self.app, "browser", None)
        if br is None:
            return
        for label, v in br._type_ids.items():
            if v == t:
                br.type_filter.set(label)
                br.rebuild()
                br.nb.select(br.banks_tab)
                self.status.config(text="Banks list: only %s scenes" % label)
                return
        self.status.config(text="type %d has no scenes in this rf3.mc" % t)

    @staticmethod
    def _show_fn(det, r):
        det.config(state="normal")
        det.delete("1.0", "end")
        if r:
            kind, key = r[4]
            det.insert("1.0", op_info_text(key) if kind == "op" else control_info_text(key))
        det.config(state="disabled")

    def _simple(self, title, cols, widths, choices, note):
        f = ttk.Frame(self.nb, padding=6)
        self.nb.add(f, text=title)
        ttk.Label(f, foreground="#666", text=note + " Double-click = copy.").pack(anchor="w", pady=(0, 4))
        t = _Filtered(f, cols, widths, list(choices), on_activate=lambda r: r and self.copy(r[1]))
        t.pack(fill="both", expand=True)


# ---- the instruction picker ------------------------------------------------------------ #
def _arg_spec(op, i, a):
    """(kind, [(display, token)], default token) of argument `i` of action `op`."""
    ch = script.enum_arg_choices(op, i)
    if ch:
        opts = [("%s  %s" % (v, lab), meta.value_name(op, i, v) or str(v)) for v, lab, _d in ch]
        return "enum", opts, opts[0][1]
    k = script.leaf_slot_kind(op, i)
    if k == "actor":
        return "actor", character_choices(), "actor(player)"
    if k == "map":
        opts = map_choices()
        return "map", opts, opts[0][1] if opts else "0"
    typ = (a.get("type") or "").lower()
    if "item id" in typ:
        return "item", item_choices(), "0"
    if typ in ("bool", "0/1", "flag"):
        return "enum", [("0  no / off", "0"), ("1  yes / on", "1")], "0"
    return "text", [], "0"


def coordinate_pairs(args):
    """[(i_x, i_y)] of absolute map-position argument pairs: an argument named x followed by
    one named y, not a relative offset. Script coordinates are 1/8-tile units (sub-units):
    the handlers store value << 12 as the actor's world position (e.g. SpawnEventActor,
    RF4S.exe+0x213660), and a live read of the game matches the map at 8 per tile."""
    out = []
    for i in range(len(args) - 1):
        a, b = args[i], args[i + 1]
        if (a.get("name") or "").lower() == "x" and (b.get("name") or "").lower() == "y":
            typ = ((a.get("type") or "") + " " + (b.get("type") or "")).lower()
            if "offset" not in typ:
                out.append((i, i + 1))
    return out


def map_arg_index(op, args):
    """Index of `op`'s map argument (a map() leaf slot or an argument named 'map'), or None."""
    for i, a in enumerate(args):
        if script.leaf_slot_kind(op, i) == "map" or (a.get("name") or "").lower() == "map":
            return i
    return None


def position_map(op, args, arg_value, bank):
    """(map id | None, lock reason | None, note, map arg index | None) for picking an x / y of
    `op`. The position is on the map the op names (its map argument) when it has one, else
    on the map the scene runs on: a map's own (tail) bank runs on that map, so it is fixed;
    a primary / global bank is not tied to a map, so the user chooses. `arg_value(i)` gives
    argument i's constant (int) or None when it is not a constant."""
    mi = map_arg_index(op, args)
    if mi is not None:
        mid = arg_value(mi)
        if mid is not None:
            return mid, "this instruction's map argument (%s) says which map the position is on; "\
                        "change that argument to use another map" % args[mi]["name"], "", mi
        return None, None, ("the map argument is not set to a map yet: the map you choose here is "
                            "written into it"), mi
    if bank is not None and bank.kind == "tail":
        return bank.index, ("the scene is in this map's event bank, so the instruction runs on "
                            "this map"), "", None
    return None, None, ("this scene is not tied to one map (a %s bank): choose the map it will run "
                        "on" % (bank.kind if bank is not None else "script")), None


class MapPointPicker:
    """Click a point on a rendered map: returns sub-unit (1/8 tile) x, y to `on_pick`."""

    def __init__(self, parent, map_id, x, y, on_pick, lock=None, note=None):
        """`lock` = why the map is fixed (the op runs on the scene's map, or takes it from a
        map argument): the map cannot be changed here. Without it the map can be chosen, and
        `note` says what the choice means."""
        from map_editor.view import MapView
        self.on_pick = on_pick
        self.map_id = None
        self.win = tk.Toplevel(parent)
        self.win.title(self.TITLE)
        self.win.geometry("1000x760")
        top = ttk.Frame(self.win)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Label(top, text="Map").pack(side="left")
        maps = map_choices()
        self._map_tok = {d: t for d, t in maps}
        self.map_cb = FilterCombo(top, [d for d, _t in maps], on_pick=self._map_picked, width=60)
        self.map_cb.pack(side="left", padx=4)
        self.locked = bool(lock and map_id is not None)
        if self.locked:
            self.map_cb.state(["disabled"])
        why = ("fixed: " + lock) if self.locked else (note or "")
        if why:
            ttk.Label(self.win, text=why, foreground="#2a6a8a" if self.locked else "#8a5a00",
                      wraplength=960, justify="left").pack(anchor="w", padx=8, before=None)
        self.grid_var = tk.BooleanVar(value=MapPointPicker.show_grid)
        gc = ttk.Checkbutton(top, text="grid", variable=self.grid_var, command=self._grid)
        gc.pack(side="left", padx=(8, 0))
        Tip(gc, "Tile grid lines (one square = one tile = 8 units; drawn from 4 px per tile up, "
                "so zoom in if they don't show).")
        self.readout = ttk.Label(top, foreground="#555")
        self.readout.pack(side="left", padx=8)
        ttk.Label(self.win, foreground="#666", text=self.HELP).pack(anchor="w", padx=8)
        self.view = MapView(self.win, on_hover_tile=None)
        self.view.pack(fill="both", expand=True, padx=6, pady=4)
        self.view.on_zoom = self._draw
        c = self.view.canvas
        c.bind("<Button-1>", self._click)
        c.bind("<Double-Button-1>", lambda e: (self._click(e), self._use()))
        c.bind("<Motion>", self._hover, add="+")
        bb = ttk.Frame(self.win)
        bb.pack(fill="x", padx=6, pady=6)
        ttk.Button(bb, text="Cancel", command=self.win.destroy).pack(side="right")
        ttk.Button(bb, text=self.USE_TEXT, command=self._use).pack(side="right", padx=4)
        self.pt = (x, y) if x is not None and y is not None else None
        if map_id is not None:
            self.load(map_id)

    show_grid = False                   # remembered for the session
    TITLE = "Pick a position on the map"
    USE_TEXT = "Use this position"
    HELP = ("Click = place the point · double-click = use it and close · wheel = zoom (or scroll: "
            "Options → Map editor) · "
            "middle-drag = pan. Values are in 1/8 tiles (8 per tile), as the script stores "
            "them; the white markers are this map's scripted NPC spawns.")

    def _grid(self):
        MapPointPicker.show_grid = on = bool(self.grid_var.get())
        self.view.st.layers["grid"] = on
        if self.view.doc is not None:
            self.view.invalidate("grid")

    def _map_picked(self, disp):
        tok = self._map_tok.get(disp)
        mid = script.map_leaf_value(tok[4:-1]) if tok else None
        if mid is not None:
            self.load(mid)

    def load(self, mid):
        from map_editor import data
        from map_editor.document import MapDocument
        from rf4s_modkit import rf4m
        name = data.rooms_by_id().get(mid)
        hit = data.find_extracted("%s.rf4m" % name) if name else None
        if hit is None:
            self.readout.config(text="map %s is not in the extracted game files" % mid)
            return False
        self.map_id = mid
        disp = next((d for d, t in map_choices() if t == script.map_leaf_text(mid)), name)
        self.map_cb.var.set(disp)
        v = self.view
        v.set_reader(data.folder_reader(hit.parent))
        v.set_doc(MapDocument(rf4m.Rf4mMap.load(hit), name, load_sidecars=False))
        v.st.layers["attr"] = False
        v.st.layers["grid"] = bool(self.grid_var.get())
        try:
            v.st.spawns = data.script_spawns(v.doc.base)[1]
            v.st.layers["spawns"] = True
            v.invalidate("spawn")
        except Exception:  # noqa: BLE001 -- the spawn overlay is only context
            pass
        v.request_ground()
        at = (self.pt[0] // 8, self.pt[1] // 8) if self.pt else None
        v.open_view(at=at)
        later(self.win, self._draw, 50)
        return True

    # The marker carries the view's "preview" tag: MapView._restack raises that group last
    # after every redraw (ground arriving, hover, zoom), so the map never covers it.
    MARK_TAGS = ("pickpt", "preview")

    def _draw(self):
        c = self.view.canvas
        c.delete("pickpt")
        if self.pt and self.view.doc is not None:
            cp = self.view.cp
            x, y = self.pt[0] * cp / 8.0, self.pt[1] * cp / 8.0
            r = max(6, cp // 2)
            c.create_oval(x - r, y - r, x + r, y + r, outline="#ff3050", width=2, tags=self.MARK_TAGS)
            c.create_line(x - r - 4, y, x + r + 4, y, fill="#ff3050", width=2, tags=self.MARK_TAGS)
            c.create_line(x, y - r - 4, x, y + r + 4, fill="#ff3050", width=2, tags=self.MARK_TAGS)
            c.tag_raise("pickpt")
        self._readout()

    def _readout(self, pointer=None):
        """'picked: x, y (tile) · pointer: x, y (tile)' -- both update live."""
        parts = []
        if self.pt:
            parts.append("picked: x = %d, y = %d  (tile %d, %d)" % (
                self.pt[0], self.pt[1], self.pt[0] // 8, self.pt[1] // 8))
        if pointer is not None:
            parts.append("pointer: x = %d, y = %d  (tile %d, %d)" % (
                pointer[0], pointer[1], pointer[0] // 8, pointer[1] // 8))
        self.readout.config(text="    ·    ".join(parts))

    def _hover(self, e):
        if self.view.doc is None:
            return
        self._readout(self.view.subunit_at(e))

    def _click(self, e):
        if self.view.doc is None:
            return
        self.pt = self.view.subunit_at(e)
        self._draw()
        self._readout(self.pt)

    def _use(self):
        if self.pt:
            self.on_pick(self.pt[0], self.pt[1], self.map_id)
            self.win.destroy()


class MapBoxPicker(MapPointPicker):
    """Drag a box on a rendered map: returns sub-unit x1, y1, x2, y2 (normalised) to `on_pick`."""

    TITLE = "Draw a box on the map"
    USE_TEXT = "Use this box"
    HELP = ("Drag = draw the box · wheel = zoom (or scroll: Options → Map editor) · middle-drag = "
            "pan. Values are in 1/8 tiles "
            "(8 per tile), the units trigger boxes compare the player's position in.")

    def __init__(self, parent, map_id, box, on_pick, lock=None, note=None):
        self.box = self._norm(box) if box else None
        self._start = None
        super().__init__(parent, map_id, None, None, on_pick, lock=lock, note=note)
        c = self.view.canvas
        c.bind("<Button-1>", self._press)
        c.bind("<B1-Motion>", self._drag)
        c.bind("<ButtonRelease-1>", self._release)
        c.unbind("<Double-Button-1>")

    @staticmethod
    def _norm(b):
        x1, y1, x2, y2 = b
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)

    def load(self, mid):
        ok = super().load(mid)
        if ok and self.box:
            x1, y1, x2, y2 = self.box
            v = self.view
            later(self.win, lambda: v.center_on((x1 + x2) / 16.0, (y1 + y2) / 16.0), 80)
        return ok

    def _draw(self):
        c = self.view.canvas
        c.delete("pickpt")
        if self.box and self.view.doc is not None:
            cp = self.view.cp
            x1, y1, x2, y2 = (v * cp / 8.0 for v in self.box)
            c.create_rectangle(x1, y1, x2, y2, outline="#ff3050", width=2, tags=self.MARK_TAGS)
            c.create_rectangle(x1, y1, x2, y2, outline="", fill="#ff3050", stipple="gray25",
                               tags=self.MARK_TAGS)
            c.tag_raise("pickpt")
        self._readout()

    def _readout(self, pointer=None):
        parts = []
        if self.box:
            x1, y1, x2, y2 = self.box
            parts.append("box: x = %d, y = %d, w = %d, h = %d  (tiles %d, %d – %d, %d)" % (
                x1, y1, x2 - x1, y2 - y1, x1 // 8, y1 // 8, x2 // 8, y2 // 8))
        if pointer is not None:
            parts.append("pointer: x = %d, y = %d" % pointer)
        self.readout.config(text="    ·    ".join(parts))

    def _press(self, e):
        if self.view.doc is None:
            return
        self._start = self.view.subunit_at(e)
        self.box = self._start + self._start
        self._draw()

    def _drag(self, e):
        if self._start is None or self.view.doc is None:
            return
        self.box = self._norm(self._start + self.view.subunit_at(e))
        self._draw()
        self._readout(self.view.subunit_at(e))

    def _release(self, e):
        self._drag(e)
        self._start = None

    def _use(self):
        if self.box:
            self.on_pick(*self.box, self.map_id)
            self.win.destroy()


class _Field:
    """One labelled input: an editable, filterable combobox (display -> token) or an entry."""

    def __init__(self, parent, row, label, hint, options, default, on_change, width=46):
        self.row = row
        self.opts = dict(options)
        self.parts = []                         # the label, input and hint (hide / show)
        lab = ttk.Label(parent, text=label)
        lab.grid(row=row, column=0, sticky="nw", padx=(0, 6), pady=2)
        self.parts.append(lab)
        self.var = tk.StringVar()
        if options:
            w = FilterCombo(parent, [d for d, _t in options], on_pick=lambda _t: on_change(), width=width,
                            textvariable=self.var)
            disp = next((d for d, t in options if t == default), default)
            self.var.set(disp)
        else:
            w = ttk.Entry(parent, textvariable=self.var, width=width + 3)
            self.var.set(default)
        w.grid(row=row, column=1, sticky="we", pady=2)
        self.widget = w
        self.parts.append(w)
        Tip(w, (label[:1].upper() + label[1:]) + (": " + hint if hint else "")
            + ". It fills in the listing below.")
        if hint:
            h = ttk.Label(parent, text=hint, foreground="#777", wraplength=380, justify="left",
                          font=("Segoe UI", 8))
            h.grid(row=row + 1, column=1, sticky="w")
            self.parts.append(h)
        self.var.trace_add("write", lambda *_a: on_change())

    def hide(self):
        for w in self.parts:
            w.grid_remove()

    def show(self):
        for w in self.parts:
            w.grid()

    def token(self):
        v = self.var.get().strip()
        return self.opts.get(v, v)


class InstructionPicker:
    """Pick any instruction, fill in its arguments, preview the listing, insert it."""

    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.frame)
        self.win.title("Cutscene Editor — Add an instruction")
        self.win.geometry("1150x700")
        self.key = None                 # ("op", n) | ("ctl", mnemonic)
        self.dlg_mode = tk.StringVar(value="new")      # DIALOG: a new line or an existing one
        self.choice_mode = tk.StringVar(value="jump")  # choice menu: "jump" | "reg0" (see _choice_ui)
        self.fields = []
        self.rows = []                  # repeating rows (targets / choice options)
        self.manual = False
        self._pending = None
        pw = ttk.PanedWindow(self.win, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=6, pady=6)
        left = ttk.Frame(pw)
        pw.add(left, weight=1)
        top = ttk.Frame(left)
        top.pack(fill="x")
        ttk.Label(top, text="Search").pack(side="left")
        self.q = tk.StringVar()
        se = ttk.Entry(top, textvariable=self.q)
        se.pack(side="left", fill="x", expand=True, padx=4)
        Tip(se, "Filter the instructions by name, opcode number or description.")
        self.only_ver = tk.BooleanVar(value=False)
        vc = ttk.Checkbutton(left, text="only instructions verified in game", variable=self.only_ver,
                             command=self.fill_tree)
        vc.pack(anchor="w")
        Tip(vc, "List only the instructions someone has checked in the running game.")
        tf = ttk.Frame(left)
        tf.pack(fill="both", expand=True, pady=(4, 0))
        self.tree = ttk.Treeview(tf, columns=("op", "v"), show="tree headings")
        self.tree.heading("#0", text="instruction")
        self.tree.heading("op", text="opcode")
        self.tree.heading("v", text="✓")
        self.tree.column("#0", width=250)
        self.tree.column("op", width=80, anchor="w")
        self.tree.column("v", width=24, anchor="center")
        sb = ttk.Scrollbar(tf, command=self.tree.yview)
        self.tree.config(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._picked)
        self.q.trace_add("write", lambda *_a: self._schedule_tree())

        right = ttk.Frame(pw, padding=(8, 0))
        pw.add(right, weight=2)
        self.title = ttk.Label(right, font=("Segoe UI", 11, "bold"))
        self.title.pack(anchor="w")
        self.desc = ttk.Label(right, wraplength=680, justify="left", foreground="#444")
        self.desc.pack(anchor="w", pady=(2, 6))
        self.form = ttk.Frame(right)
        self.form.pack(fill="x")
        self.form.columnconfigure(1, weight=1)
        ttk.Separator(right).pack(fill="x", pady=6)
        ph = ttk.Frame(right)
        ph.pack(fill="x")
        ttk.Label(ph, text="Listing (what gets inserted — you can also edit it by hand):").pack(side="left")
        self.rebuild_btn = ttk.Button(ph, text="Rebuild from the form", command=self._rebuild)
        Tip(self.rebuild_btn, "Throw away your hand edits of the listing and write it again from "
                              "the form.")
        self.preview = tk.Text(right, height=7, font=("Consolas", 10), wrap="none", undo=True)
        self.preview.pack(fill="both", expand=True)
        self.preview.bind("<Key>", self._typed)
        self.check_lbl = ttk.Label(right, wraplength=680, justify="left")
        self.check_lbl.pack(anchor="w", pady=(4, 0))
        bb = ttk.Frame(right)
        bb.pack(fill="x", pady=(6, 0))
        self.where = tk.StringVar(value="after")
        ra = ttk.Radiobutton(bb, text="after the selected statement", value="after", variable=self.where)
        ra.pack(side="left")
        Tip(ra, "Insert goes right after the statement selected in the Script tab.")
        rb_ = ttk.Radiobutton(bb, text="before it", value="before", variable=self.where)
        rb_.pack(side="left", padx=6)
        Tip(rb_, "Insert goes right before the selected statement (so also where a jump to it lands).")
        cb = ttk.Button(bb, text="Close", command=self.win.withdraw)
        cb.pack(side="right")
        Tip(cb, "Hide this window (it keeps what you filled in).")
        ib = ttk.Button(bb, text="Insert", command=self.insert)
        ib.pack(side="right", padx=4)
        Tip(ib, "Insert the listing at the selected statement of the open scene (Ctrl+Enter) "
                "and close this window; the new statement is selected in the script. If it "
                "can't be inserted the window stays open and says why.")
        sb2 = ttk.Button(bb, text="Whole scene in the Source tab", command=self._source_tab)
        sb2.pack(side="right", padx=4)
        Tip(sb2, "Prefer typing? The Source tab has the whole scene as editable listing text.")
        self.win.bind("<Control-Return>", lambda _e: (self.insert(), "break")[1])
        self.win.protocol("WM_DELETE_WINDOW", self.win.withdraw)
        self._tree_pending = None
        self.fill_tree()

    # ---- the list ---------------------------------------------------------------- #
    def _schedule_tree(self):
        if self._tree_pending is not None:
            self.win.after_cancel(self._tree_pending)
        self._tree_pending = later(self.win, self.fill_tree, 150)

    def entries(self):
        """[(group, iid, text, opcode text, verified, search text)] -- control instructions,
        then every named action op by category (a family such as SetSpeaker once)."""
        out = []
        for m in CONTROL_ORDER:
            r = next((x for x in meta.TABLE["control"].values() if x["mnemonic"] == m), {})
            out.append((CONTROL_GROUP, "ctl:" + m, m, r.get("op_hex", ""), bool(r.get("human_verified")),
                        "%s %s %s" % (m, CONTROL_HELP.get(m, ""), r.get("description", ""))))
        seen_fam = set()
        for op in range(script.DISPATCHABLE_ACTION_OPS):
            m = meta.mnemonic(op)
            if (not m or m.startswith("(") or m in PLACEHOLDER) and op != meta.NOP_OP:
                continue
            fam = meta.OPCODE_ARGS.get(op)
            if fam:
                if m in seen_fam:
                    continue
                seen_fam.add(m)
                ops = [o for o in meta.OPCODE_ARGS if meta.mnemonic(o) == m]
                optxt = "0x%03X–0x%03X" % (min(ops), max(ops))
                ver = all(meta.human_verified(o) for o in ops)
            else:
                optxt = "0x%03X" % op
                ver = meta.human_verified(op)
            out.append((meta.category_label(op), "op:%d" % op, m, optxt, ver,
                        "%s %d %s" % (m, op, meta.describe(op) or "")))
        return out

    def fill_tree(self):
        self._tree_pending = None
        self.tree.delete(*self.tree.get_children())
        words = self.q.get().lower().split()
        groups = {}
        n = 0
        for grp, iid, text, optxt, ver, hay in self.entries():
            if self.only_ver.get() and not ver:
                continue
            if words and not all(w in hay.lower() for w in words):
                continue
            if grp not in groups:
                groups[grp] = self.tree.insert("", "end", iid="grp:" + grp, text=grp, open=bool(words))
            self.tree.insert(groups[grp], "end", iid=iid, text=text, values=(optxt, "✓" if ver else ""))
            n += 1
        if CONTROL_GROUP in groups and not words:
            self.tree.item(groups[CONTROL_GROUP], open=True)
        return n

    def _picked(self, _e=None):
        s = self.tree.selection()
        if not s or s[0].startswith("grp:"):
            return
        kind, _, key = s[0].partition(":")
        self.set_instruction((kind, int(key) if kind == "op" else key))

    def preset(self, key):
        """Show instruction `key` (('op', n) or ('ctl', mnemonic)) and select it in the list."""
        self.q.set("")
        self.fill_tree()
        iid = "%s:%s" % key
        if key[0] == "op" and meta.OPCODE_ARGS.get(key[1]):
            first = min(o for o in meta.OPCODE_ARGS if meta.mnemonic(o) == meta.mnemonic(key[1]))
            iid = "op:%d" % first
        if self.tree.exists(iid):
            self.tree.see(iid)
            self.tree.selection_set(iid)
        self.set_instruction(key)

    # ---- the form ---------------------------------------------------------------- #
    def set_instruction(self, key):
        self.key = key
        self.manual = False
        self.preview.config(state="normal")
        self.rebuild_btn.pack_forget()
        for w in self.form.winfo_children():
            w.destroy()
        self.fields = []
        self.rows = []
        if key[0] == "op":
            self._action_form(key[1])
        else:
            self._control_form(key[1])
        self._rebuild()

    def _add(self, label, hint, options, default, width=46):
        f = _Field(self.form, 2 * len(self.fields) + 10, label, hint, options, default, self._changed, width)
        self.fields.append(f)
        return f

    def _action_form(self, op):
        r = meta.table_row(op) or {}
        fam = meta.OPCODE_ARGS.get(op)
        m = meta.mnemonic(op)
        self.title.config(text=meta.prototype(op))
        ver = "✓ verified in game" if (meta.human_verified(op) if not fam else all(
            meta.human_verified(o) for o in meta.OPCODE_ARGS if meta.mnemonic(o) == m)) else "not yet verified in game"
        self.desc.config(text="%s\n%s · %s" % (meta.describe(op) or "", meta.category_label(op), ver))
        self.op_fields = []
        self.fam_fields = []
        if fam:
            ops = [o for o in meta.OPCODE_ARGS if meta.mnemonic(o) == m]
            for i, a in enumerate(fam):
                vals = []
                for o in sorted(ops):
                    v = meta.OPCODE_ARGS[o][i]["value"]
                    if v not in vals:
                        vals.append(v)
                self.fam_fields.append(self._add(a["name"], "encoded in the opcode (%s)" % a["encoding"],
                                                 [(v, v) for v in vals], a["value"], width=30))
        self.args = r.get("args") or [{"name": n} for n in meta.arg_names(op)]
        # how many arguments: the shipped game's fewest / most (meta.arg_range: a missing one
        # is read as leftover memory), else the table's optional_args_from; the last named
        # argument repeats for a variadic op
        rng = meta.arg_range(op)
        n_args = len(self.args)
        self.opt_from = rng[0] if rng else r.get("optional_args_from")
        if self.opt_from is None:
            self.opt_from = n_args
        lim = meta.arg_limit(op)
        self.max_args = min(x for x in ((rng[1] if rng else None), (lim[0] if lim else None),
                                        (None if (r.get("size") or [0, 0])[1] is None else n_args), 64)
                            if x is not None)
        self.max_args = max(self.max_args, self.opt_from, n_args if (r.get("size") or [0, 0])[1] is not None else 0)
        self.op = op
        for i in range(max(self.opt_from, min(n_args, self.max_args))):
            self._op_field(i)
        if self.max_args > len(self.op_fields):
            self.more_btn = ttk.Button(self.form, text="＋ another argument", command=self._more)
            self.more_btn.grid(row=900, column=1, sticky="w", pady=4)
        for ix, iy in coordinate_pairs(self.args):
            if iy < len(self.op_fields):
                b = ttk.Button(self.form, text="📍 Pick on map…",
                               command=lambda ix=ix, iy=iy: self.pick_on_map(ix, iy))
                b.grid(row=self.op_fields[ix].row, column=2, rowspan=2, sticky="nw", padx=4)
                Tip(b, "Click the position on the map instead of typing x and y (1/8-tile units).")
        if not self.op_fields and not fam and self.max_args == 0:
            ttk.Label(self.form, text="(no arguments)", foreground="#777").grid(row=10, column=1, sticky="w")

    def _op_field(self, i):
        """The form field of argument i (the last named argument repeats past the list)."""
        op = self.op
        a = self.args[min(i, len(self.args) - 1)] if self.args else {"name": "arg"}
        kind, opts, default = _arg_spec(op, i, a)
        hint = ((a.get("type") or "") + (": " + a["values"] if a.get("values") else ""))[:300]
        hint = ("✓ verified in game. " if a.get("human_verified") else "not verified in game. ") + hint
        label = a["name"] if i < len(self.args) else "%s #%d" % (a["name"], i - len(self.args) + 2)
        if i >= self.opt_from:
            label += " (optional)"
            default = ""
            hint = "leave empty to leave it out. " + hint
        self.op_fields.append(self._add(label, hint, opts, default))

    def _field_value(self, i):
        """Argument i's value as an int (map(MAP_X) / actor(...) leaves resolved), or None."""
        if i >= len(self.op_fields):
            return None
        t = self.op_fields[i].token()
        if t.startswith("map(") and t.endswith(")"):
            return script.map_leaf_value(t[4:-1])
        try:
            return int(t, 0)
        except ValueError:
            return None

    def position_map(self):
        """(map id, lock, note, map arg index): see position_map()."""
        return position_map(self.op, self.args, self._field_value, getattr(self.app, "bank", None))

    def scene_map_id(self):
        return self.position_map()[0]

    def pick_on_map(self, ix, iy):
        mid, lock, note, mi = self.position_map()

        def done(x, y, chosen):
            self.op_fields[ix].var.set(str(x))
            self.op_fields[iy].var.set(str(y))
            if mi is not None and mid is None and chosen is not None and mi < len(self.op_fields):
                self.op_fields[mi].var.set(script.map_leaf_text(chosen)
                                           if script.leaf_slot_kind(self.op, mi) == "map" else str(chosen))
        self._map_picker = MapPointPicker(self.win, mid, self._field_value(ix), self._field_value(iy),
                                          done, lock=lock, note=note)
        return self._map_picker

    def _more(self):
        self._op_field(len(self.op_fields))
        if len(self.op_fields) >= self.max_args:
            self.more_btn.grid_remove()
        self._changed()

    def _targets(self):
        """[(display, token)] for jump targets: the open scene's statements (0xPC)."""
        app = self.app
        out = []
        sc = getattr(app, "scene", None)
        if sc is None:
            return out
        labels = script.scene_labels(sc)
        for pc, st in sc.stmts.items():
            if st.mnem == "DIALOG":
                t = (app.doc.text(st.dialog_id) or "").replace("\n", " ")[:50]
                what = 'DIALOG "%s"' % t
            elif st.op < 0xFFF0:
                what = meta.mnemonic(st.op)
            else:
                what = st.mnem
            lab = labels.get(pc)
            out.append(("0x%04x  %s%s" % (pc, (lab + ": ") if lab else "", what), "0x%04x" % pc))
        return out

    def _subroutines(self):
        """[(display, token)] for CALL: the subroutines of the open bank -- what any of its
        scenes CALLs, and its unreached code (e.g. a subroutine whose last CALL was deleted,
        so it can be called again) -- each with a one-line preview."""
        app = self.app
        bank = getattr(app, "bank", None)
        if bank is None:
            return []
        from .render import scene_preview
        try:
            scenes = script.disassemble_bank(bank)
        except Exception:  # noqa: BLE001 -- a picker convenience
            return []
        called = {}
        for sc in scenes:
            for _pc, st in sc.stmts.items():
                if st.mnem == "CALL" and st.code_targets and st.code_targets[0] is not None:
                    called[st.code_targets[0]] = called.get(st.code_targets[0], 0) + 1
        out = []
        for t in sorted(called):
            try:
                prev = scene_preview(app.doc, script.disassemble_scene(bank, -1, t))
            except Exception:  # noqa: BLE001
                prev = ""
            out.append(("sub @%04x  (%d call%s) · %s" % (t, called[t], "" if called[t] == 1 else "s",
                                                          prev[:50]), "0x%04x" % t))
        for sc, _own in script.unreached(scenes):
            if sc.entry_pc not in called:
                out.append(("unreached @%04x · %s" % (sc.entry_pc, scene_preview(app.doc, sc)[:50]),
                            "0x%04x" % sc.entry_pc))
        return out

    def _cond(self, prefix="condition"):
        vars_ = variable_choices(self.app.doc)
        self.c_left = self._add(prefix + ": variable", "a flag / register name, or any expression",
                                vars_, vars_[10][1] if len(vars_) > 10 else "reg0")
        self.c_cmp = self._add("compare", "", [(c, c) for c in ("==", "!=", ">", ">=", "<", "<=", "(is non-zero)")],
                               "==", width=14)
        self.c_right = self._add("value", "", [], "1", width=14)

    def _cond_text(self):
        cmp = self.c_cmp.token()
        if cmp == "(is non-zero)":
            return "(%s)" % self.c_left.token()
        return "(%s %s %s)" % (self.c_left.token(), cmp, self.c_right.token())

    def _control_form(self, m):
        r = next((x for x in meta.TABLE["control"].values() if x["mnemonic"] == m), {})
        self.title.config(text=r.get("prototype") or m)
        self.desc.config(text=CONTROL_HELP.get(m, ""))
        tg = self._targets()
        tdef = tg[0][1] if tg else "0x0000"
        if m == "DIALOG":
            from . import dialogs
            mr = ttk.Frame(self.form)
            mr.grid(row=5, column=0, columnspan=3, sticky="w", pady=(0, 4))
            for val, lab, tip in (("new", "a new line", "Write a new line: its speaker, face, box "
                                                        "style and text. Insert adds it in every locale."),
                                  ("existing", "an existing line", "Show a line that already exists, "
                                                                   "by its id (Find a line… searches them).")):
                rb = ttk.Radiobutton(mr, text=lab, value=val, variable=self.dlg_mode,
                                     command=self._dialogue_mode)
                rb.pack(side="left", padx=(0, 10))
                Tip(rb, tip)
            # a new line: speaker (+ side, face), box style and text; added in every locale
            self.dlg_form = dialogs.DialogueForm(self.form, reader=self.app.doc.reader,
                                                 on_change=self._changed)
            self.dlg_form.frame.grid(row=6, column=0, columnspan=3, sticky="we")
            # an existing line by id
            self.line = self._add("line id", "the dialogue line (#id) in rf3mc.<locale>", [], "0", width=14)
            self.line_btns = ttk.Frame(self.form)
            self.line_btns.grid(row=99, column=1, sticky="w", pady=4)
            fb = ttk.Button(self.line_btns, text="Find a line…", command=self._find_line)
            fb.pack(side="left")
            Tip(fb, "Search this locale's dialogue for a line and use its id.")
            self.line_txt = ttk.Label(self.form, foreground="#555", wraplength=520, justify="left")
            self.line_txt.grid(row=100, column=1, sticky="w")
            self._dialogue_mode(rebuild=False)
        elif m == "EVAL":
            vars_ = variable_choices(self.app.doc)
            self.e_var = self._add("variable", "flag / register to change", vars_, vars_[10][1] if len(vars_) > 10 else "reg0")
            self.e_op = self._add("operation", "", [(o, o) for o in ("=", "+=", "-=", "*=", "/=", "%=", "&&=", "||=")], "=", width=14)
            self.e_val = self._add("value", "a number or an expression", [], "1", width=20)
        elif m in ("BR_Z", "BR_NZ", "RET_NZ"):
            self._cond()
            if m != "RET_NZ":
                self.t1 = self._add("target", "where to jump (a statement of this scene)", tg, tdef)
        elif m == "CALL":
            subs = self._subroutines()
            self.t1 = self._add("target", "a subroutine of this bank (every scene's CALL targets and "
                                          "the unreached code), or a statement of this scene",
                                subs + tg, subs[0][1] if subs else tdef)
        elif m == "JMP":
            self.t1 = self._add("target", "a statement of this scene", tg, tdef)
        elif m == "FRAME":
            self.n = self._add("stack words", "an even number; the editor sizes it by itself", [], "2", width=14)
        elif m in ("SWITCH", "SWITCH_CLAMP"):
            vars_ = variable_choices(self.app.doc)
            self.sel_f = self._add("selector", "the value that picks the target", vars_, "reg0")
            self._rows_ui("targets (0, 1, 2, …)", [("target", tg, tdef)], 2)
        elif m == "JMP_RAND":
            self._rows_ui("targets", [("target", tg, tdef)], 2)
        elif m == "JMP_WEIGHTED":
            self._rows_ui("weighted targets", [("weight", [], "1"), ("target", tg, tdef)], 2)
        elif m in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED"):
            self._choice_ui(tg, tdef)
        else:
            ttk.Label(self.form, text="(no operands)", foreground="#777").grid(row=10, column=1, sticky="w")

    def _rows_ui(self, title, cols, n):
        box = ttk.LabelFrame(self.form, text=title, padding=4)
        box.grid(row=200, column=0, columnspan=2, sticky="we", pady=4)
        self._rows_box, self._rows_cols = box, cols
        ttk.Button(box, text="＋ add", command=self._add_row).pack(anchor="w")
        for _ in range(n):
            self._add_row(render=False)

    def _add_row(self, render=True):
        f = ttk.Frame(self._rows_box)
        f.pack(fill="x", pady=1, before=self._rows_box.winfo_children()[0])
        row = []
        for label, opts, default in self._rows_cols:
            ttk.Label(f, text=label).pack(side="left", padx=(4, 2))
            var = tk.StringVar()
            if opts:
                w = FilterCombo(f, [d for d, _t in opts], on_pick=lambda _t: self._changed(),
                                width=34, textvariable=var)
                var.set(next((d for d, t in opts if t == default), default))
            else:
                w = ttk.Entry(f, textvariable=var, width=8)
                var.set(default)
            w.pack(side="left")
            var.trace_add("write", lambda *_a: self._changed())
            row.append((var, dict(opts)))
        rm = ttk.Button(f, text="✕", width=3)
        rm.pack(side="left", padx=4)
        entry = (f, row)
        rm.config(command=lambda: self._del_row(entry))
        self.rows.append(entry)
        if render:
            self._changed()

    def _del_row(self, entry):
        if entry in self.rows and len(self.rows) > 1:
            self.rows.remove(entry)
            entry[0].destroy()
            self._changed()

    def _row_tokens(self):
        return [[opts.get(v.get().strip(), v.get().strip()) for v, opts in row] for _f, row in self.rows]

    # ---- choice menus -------------------------------------------------------------- #
    # One opcode, two ways the shipped scripts use it (Script_VMStep 0xFFF4 / 0xFFF5 always
    # jumps to the target of the picked VISIBLE row; SceneEvent_FinalizeAndPickFromBitmap
    # RF4S.exe+0x1F49C0 writes reg0 = the picked option's ORIGINAL index, but only when a
    # visibility op (610 / 611 / 612) set a bit of the mask before the menu):
    #   "jump": every option has its own target -- the menu jumps there directly;
    #   "reg0": SetChoiceVisibleBit(k, show-when) per option, every option -> one label,
    #           then SWITCH (reg0) -> the options' targets. Options can be hidden, and the
    #           answer stays readable in reg0 (the shipped menus' usual form, 350 of them).
    CHOICE_NEXT = "<next>"
    CHOICE_NEXT_DISP = "→ continue after the menu"
    CHOICE_SKIP_DISP = "→ skip the menu (continue after it)"

    def _choice_ui(self, tg, tdef):
        opts = [(self.CHOICE_NEXT_DISP, self.CHOICE_NEXT)] + tg
        self._choice_opts = opts
        self._choice_meta = {}
        mf = ttk.Frame(self.form)
        mf.grid(row=5, column=0, columnspan=3, sticky="w", pady=(0, 2))
        ttk.Label(mf, text="When the player picks an option:").pack(side="left", padx=(0, 8))
        for val, lab, tip in (
                ("jump", "jump to its target",
                 "Each option jumps straight to its own target. Simple, but every option is "
                 "always shown and nothing remembers which one was picked."),
                ("reg0", "store the answer in reg0, then branch",
                 "The answer (0 = first option, 1 = second, …) goes into reg0, then a SWITCH "
                 "on reg0 sends each answer to its target. Lets you hide options with a "
                 "'show when' condition, and later code can still read reg0. This is how most "
                 "of the game's own menus are built.")):
            rb = ttk.Radiobutton(mf, text=lab, value=val, variable=self.choice_mode,
                                 command=self._choice_mode_changed)
            rb.pack(side="left", padx=(0, 10))
            Tip(rb, tip)
        self._choice_hint = ttk.Label(self.form, foreground="#777", wraplength=640, justify="left",
                                      font=("Segoe UI", 8))
        self._choice_hint.grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 4))
        box = ttk.LabelFrame(self.form, text="options (top to bottom as they appear in the menu)",
                             padding=4)
        box.grid(row=200, column=0, columnspan=2, sticky="we", pady=4)
        self._rows_box = box
        self._choice_rows_frame = ttk.Frame(box)
        self._choice_rows_frame.pack(fill="x")
        ab = ttk.Button(box, text="＋ add option", command=self._choice_add_row)
        ab.pack(anchor="w", pady=(4, 0))
        Tip(ab, "Add another option at the bottom of the menu.")
        for _ in range(2):
            self._choice_add_row(render=False)
        gf = ttk.Frame(self.form)
        gf.grid(row=201, column=0, columnspan=2, sticky="we", pady=(0, 4))
        ttk.Label(gf, text="If no option would be shown:").pack(side="left", padx=(0, 6))
        self._choice_guard = tk.StringVar(value=self.CHOICE_SKIP_DISP)
        gopts = [(self.CHOICE_SKIP_DISP, self.CHOICE_NEXT)] + tg
        self._choice_guard_opts = dict(gopts)
        gc = FilterCombo(gf, [d for d, _t in gopts], on_pick=lambda _t: self._changed(), width=40,
                         textvariable=self._choice_guard)
        gc.pack(side="left", fill="x", expand=True)
        Tip(gc, "When every option's condition is false, the game would show ALL the options "
                "and send any pick to the first option's branch. The form adds a check before "
                "the menu (BR_Z (reg0)) that goes here instead. Not added when an option is "
                "always shown.")
        self._choice_guard_row = gf
        self._choice_guard.trace_add("write", lambda *_a: self._changed())
        self._choice_mode_changed(rebuild=False)

    def _choice_add_row(self, render=True):
        f = ttk.Frame(self._choice_rows_frame)
        f.pack(fill="x", pady=1)
        num = ttk.Label(f, width=3, anchor="e")
        num.pack(side="left")
        line = tk.StringVar(value="0")
        le = ttk.Entry(f, textvariable=line, width=8)
        le.pack(side="left", padx=(4, 0))
        Tip(le, "The dialogue line (#id) this option shows.")
        # packed right to left after the line id, the option's text last: a narrow window
        # squeezes the text preview, never the target
        txt = ttk.Label(f, width=12, foreground="#555", anchor="w")
        fb = ttk.Button(f, text="…", width=2, command=lambda: self._choice_find_line(line))
        fb.pack(side="left")
        Tip(fb, "Search this locale's dialogue for the option's text and use its id.")
        cl = ttk.Label(f, text="show when")
        cond = tk.StringVar(value="always")
        ce = ttk.Entry(f, textvariable=cond, width=16)
        Tip(ce, "'always', or a condition such as FLG_SOMETHING, reg1 == 2 or "
                "FLG_A && !FLG_B: the option is only shown while it is true. Don't read "
                "reg0 here: each SetChoiceVisibleBit sets reg0 (1 = some option is shown), "
                "so copy it to another register first.")
        cond_parts = [cl, ce]
        rm = ttk.Button(f, text="✕", width=3)
        tgt = tk.StringVar()
        tc = FilterCombo(f, [d for d, _t in self._choice_opts], on_pick=lambda _t: self._changed(),
                         width=28, textvariable=tgt)
        tgt.set(self.CHOICE_NEXT_DISP)
        Tip(tc, "Where this answer continues: a statement of this scene, or straight on "
                "after the menu.")
        arrow = ttk.Label(f, text="→")
        rm.pack(side="right", padx=4)
        tc.pack(side="right")
        arrow.pack(side="right", padx=(2, 4))
        txt.pack(side="left", fill="x", expand=True, padx=(4, 6))
        row = [(line, {}), (cond, {"always": "1", "": "1"}), (tgt, dict(self._choice_opts))]
        entry = (f, row)
        entry_meta = {"num": num, "txt": txt, "cond": cond_parts}
        rm.config(command=lambda: self._choice_del_row(entry))
        Tip(rm, "Remove this option.")
        self.rows.append(entry)
        self._choice_meta[id(entry)] = entry_meta
        line.trace_add("write", lambda *_a: (self._choice_line_text(line, txt), self._changed()))
        cond.trace_add("write", lambda *_a: self._changed())
        tgt.trace_add("write", lambda *_a: self._changed())
        self._choice_line_text(line, txt)
        self._choice_refresh()
        if render:
            self._changed()

    def _choice_del_row(self, entry):
        if entry in self.rows and len(self.rows) > 1:
            self.rows.remove(entry)
            entry[0].destroy()
            self._choice_refresh()
            self._changed()

    def _choice_refresh(self):
        """Number the rows and show / hide the 'show when' column for the mode."""
        reg0 = self.choice_mode.get() == "reg0"
        for k, entry in enumerate(self.rows):
            mt = self._choice_meta.get(id(entry))
            if not mt:
                continue
            mt["num"].config(text="%d." % (k + 1))
            cl, ce = mt["cond"]
            if reg0:
                ce.pack(side="right", before=mt["txt"])
                cl.pack(side="right", padx=(6, 4), before=mt["txt"])
            else:
                ce.pack_forget()
                cl.pack_forget()

    def _choice_mode_changed(self, rebuild=True):
        reg0 = self.choice_mode.get() == "reg0"
        cancel = self.key == ("ctl", "PROMPT_CHOICE")
        if reg0:
            hint = ("Inserts one SetChoiceVisibleBit per option, the menu, and a SWITCH on reg0 "
                    "that sends each answer to its target. reg0 = the option's number counted "
                    "from 0 in this list, also when options above it are hidden. Make sure at least "
                    "one condition is true: with none, the game shows every option and any pick "
                    "goes to the first option's target, so the form adds a check that goes "
                    "to 'If no option would be shown' instead. Conditions can't read reg0 "
                    "(the SetChoiceVisibleBit lines overwrite it).")
        else:
            hint = ("Every option is shown and jumps straight to its target. To hide options "
                    "or keep the answer for later, pick 'store the answer in reg0'.")
        if cancel:
            hint += " Cancel picks the last option."
        self._choice_hint.config(text=hint)
        if reg0:
            self._choice_guard_row.grid()
        else:
            self._choice_guard_row.grid_remove()
        self._choice_refresh()
        if rebuild:
            self._changed()

    def _choice_line_text(self, var, label):
        t = None
        try:
            t = self.app.doc.text(int(var.get().strip().lstrip("#")))
        except (ValueError, TypeError, AttributeError):
            pass
        t = (t or "").replace("\n", " ")
        try:
            label.config(text=('"%s"' % (t[:30] + ("…" if len(t) > 30 else ""))) if t
                         else "(no such line)", foreground="#555" if t else "#b00")
        except tk.TclError:
            pass

    def _choice_find_line(self, var):
        from . import dialogs
        i = dialogs.pick_line(self.win, self.app.doc)
        if i is not None:
            var.set(str(i))

    @staticmethod
    def _always_shown(cond):
        try:
            return int(cond or "1", 0) != 0
        except ValueError:
            return False

    def _choice_listing(self, m):
        """The listing of the choice form: the menu alone ("jump"), or the visibility ops +
        menu + SWITCH (reg0) ("reg0"). '<next>' targets land on a label after the block."""
        rows = [(line.lstrip("#") or "0", cond, tgt) for line, cond, tgt in self._row_tokens()]
        uses_next = False

        def target(t):
            nonlocal uses_next
            if t == self.CHOICE_NEXT:
                uses_next = True
                return "L_after_menu"
            return t

        out = []
        if self.choice_mode.get() == "reg0":
            for k, (_line, cond, _t) in enumerate(rows):
                out.append("SetChoiceVisibleBit(%d, %s)" % (k, cond or "1"))
            if not any(self._always_shown(cond) for _l, cond, _t in rows):
                # every option can be hidden: an empty mask would show them all and leave
                # reg0 = 0 (script.choice_empty_mask_problems) -- reg0 = 'any shown' here
                g = self._choice_guard.get().strip()
                out.append("BR_Z (reg0) -> %s" % target(self._choice_guard_opts.get(g, g)))
            if all(t == self.CHOICE_NEXT for _l, _c, t in rows):
                dest = target(self.CHOICE_NEXT)       # nothing to branch on: just keep reg0
                out.append("%s %s" % (m, ", ".join("#%s -> %s" % (line, dest) for line, _c, _t in rows)))
            else:
                out.append("%s %s" % (m, ", ".join("#%s -> L_answer" % line for line, _c, _t in rows)))
                out.append("L_answer:")
                out.append("SWITCH (reg0) -> " + ", ".join(target(t) for _l, _c, t in rows))
        else:
            out.append("%s %s" % (m, ", ".join("#%s -> %s" % (line, target(t)) for line, _c, t in rows)))
        if uses_next:
            out.append("L_after_menu:")
        return "\n".join(out)

    # ---- the listing ------------------------------------------------------------- #
    def listing(self):
        """The listing text of the form as filled in."""
        kind, key = self.key
        if kind == "op":
            op = key
            if self.fam_fields:
                op = meta.op_from_opcode_args(meta.mnemonic(key), [f.token() for f in self.fam_fields])
            args = [f.token() for f in self.op_fields]
            last = min(self.opt_from, len(args))       # optional args: up to the last one given
            for i in range(last, len(args)):
                if args[i]:
                    last = i + 1
            rng = meta.arg_range(op)                   # a family member may need more (SetSpeaker)
            last = max(last, min(rng[0], len(args)) if rng else 0)
            return scriptasm.action_line(op, [a or "0" for a in args[:last]])
        m = key
        if m == "DIALOG" and self.dlg_mode.get() == "new":
            spec, _err = self.dlg_form.value()
            out = []
            if spec and spec["speaker"] is not None:
                out.append("op%d %d, 0" % (script.portrait_opcode(*spec["speaker"]), int(spec["face"] or 0)))
            box = spec["box"] if spec else None
            if box is not None:
                out.append("op%d" % (94 + box) if 0 <= box <= 3 else "op93 %d" % box)
            out.append("DIALOG #(new)")
            return "\n".join(out)
        if m == "DIALOG":
            return "DIALOG #%s" % self.line.token()
        if m == "EVAL":
            return "EVAL (%s %s %s)" % (self.e_var.token(), self.e_op.token(), self.e_val.token())
        if m in ("BR_Z", "BR_NZ"):
            return "%s %s -> %s" % (m, self._cond_text(), self.t1.token())
        if m == "RET_NZ":
            return "RET_NZ %s" % self._cond_text()
        if m in ("JMP", "CALL"):
            return "%s %s" % (m, self.t1.token())
        if m == "FRAME":
            return "FRAME %s" % self.n.token()
        rows = self._row_tokens()
        if m in ("SWITCH", "SWITCH_CLAMP"):
            return "%s (%s) -> %s" % (m, self.sel_f.token(), ", ".join(r[0] for r in rows))
        if m == "JMP_RAND":
            return "JMP_RAND " + ", ".join(r[0] for r in rows)
        if m == "JMP_WEIGHTED":
            return "JMP_WEIGHTED " + ", ".join("(%s) -> %s" % (w, t) for w, t in rows)
        if m in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED"):
            return self._choice_listing(m)
        return m

    def _changed(self):
        if self._pending is not None:
            self.win.after_cancel(self._pending)
        self._pending = later(self.win, self._rebuild_if_auto, 120)

    def _rebuild_if_auto(self):
        self._pending = None
        if not self.manual:
            self._rebuild()

    def _rebuild(self):
        self.manual = False
        self.rebuild_btn.pack_forget()
        try:
            text = self.listing() if self.key else ""
        except Exception as e:  # noqa: BLE001 -- e.g. an opcode argument that names nothing
            text = ""
            self.check_lbl.config(text="✗ %s" % err_text(e), foreground="#b00")
        state = str(self.preview.cget("state"))
        self.preview.config(state="normal")             # a new line's preview is read-only
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.config(state=state)
        if getattr(self, "line_txt", None) is not None and self.key == ("ctl", "DIALOG"):
            try:
                t = self.app.doc.text(int(self.line.token().lstrip("#")))
            except (ValueError, TypeError):
                t = None
            try:
                self.line_txt.config(text=('"%s"' % t) if t else "(no such line in this locale)")
            except tk.TclError:
                pass
        self.check()

    def _typed(self, _e=None):
        if not self.manual:
            self.manual = True
            self.rebuild_btn.pack(side="right")
        later(self.win, self.check, 50)

    def text(self):
        return self.preview.get("1.0", "end").strip()

    def _new_dialogue(self):
        return self.key == ("ctl", "DIALOG") and self.dlg_mode.get() == "new"

    def check(self):
        if self._new_dialogue():
            _spec, err = self.dlg_form.value()
            self.check_lbl.config(text=("✗ " + err) if err else
                                  "✓ a new line: Insert adds it in every locale",
                                  foreground="#b00" if err else "#080")
            return not err
        text = self.text()
        if not text:
            return False
        err = self.app.assemble_check(text)[2] if self.app.doc.container is not None else "no rf3.mc loaded"
        warn = None if err else self._lint(text)
        if err:
            self.check_lbl.config(text="✗ " + err, foreground="#b00")
        elif warn:
            self.check_lbl.config(text="⚠ assembles, but: " + warn, foreground="#b06000")
        else:
            self.check_lbl.config(text="✓ assembles", foreground="#080")
        return not err

    def _lint(self, text):
        """The engine-behaviour warnings for the listing (scriptasm.lint_listing): menus that
        freeze, an empty visibility mask, … -- shown under the preview, Insert still works."""
        try:
            probs = scriptasm.lint_listing(text, resolver=self.app.doc.container.asm_resolver)
        except Exception:  # noqa: BLE001 -- e.g. a jump to an existing pc outside the snippet
            return None
        return " ".join(m for _pc, _lvl, m in probs[:2]) or None

    # ---- actions ----------------------------------------------------------------- #
    def insert(self):
        if not self.check():
            return False
        before = self.where.get() == "before"
        w = self.app._insert_where(before)
        if w is None:
            self.check_lbl.config(text="select a statement in the Script view first (the new "
                                       "instruction goes after / before it)", foreground="#b00")
            return False
        pc, before = w
        if self._new_dialogue():
            if self.app.doc.textarc is None:
                self.check_lbl.config(text="rf3mc.%s is not loaded" % self.app.doc.locale,
                                      foreground="#b00")
                return False
            spec, _err = self.dlg_form.value()
            nid = self.app._insert_dialogue(pc, spec["speaker"], spec["text"], spec.get("face", 0),
                                            spec.get("box"), before)
            if nid is not None:
                self.where.set("after")
                self.dlg_form.set_text("")
                self.check_lbl.config(text="")
                self.win.withdraw()             # done: back to the script, the new line selected
            return nid
        ok = self.app.insert_before(pc, self.text()) if before else self.app.insert_after(pc, self.text())
        if ok:
            self.where.set("after")
            self.check_lbl.config(text="")
            self.win.withdraw()                 # done: back to the script, the new one selected
        return ok

    def _find_line(self):
        from . import dialogs
        i = dialogs.pick_line(self.win, self.app.doc)
        if i is not None:
            self.line.var.set(str(i))

    def _dialogue_mode(self, rebuild=True):
        """Show the new-line form or the line-id field."""
        new = self.dlg_mode.get() == "new"
        if new:
            self.dlg_form.frame.grid()
            for w in (self.line_btns, self.line_txt):
                w.grid_remove()
            self.line.hide()
        else:
            self.dlg_form.frame.grid_remove()
            for w in (self.line_btns, self.line_txt):
                w.grid()
            self.line.show()
        try:
            self.preview.config(state="disabled" if new else "normal")
        except tk.TclError:
            pass
        if rebuild:
            self._rebuild()

    def _source_tab(self):
        try:
            self.app.nb.select(self.app.nb.index(self.app.source))
            self.app.frame.winfo_toplevel().lift()
        except (tk.TclError, AttributeError):
            pass

    def show(self, preset=None, before=None):
        self.win.deiconify()
        self.win.lift()
        if before is not None:
            self.where.set("before" if before else "after")
        if preset is not None:
            self.preset(preset)
        elif self.key is None:
            self.preset(("ctl", "DIALOG"))
