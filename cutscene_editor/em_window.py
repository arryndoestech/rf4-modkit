"""The Event Manager window: em.bin's 272 entries -- the rules the game asks "is this true
right now?" -- browsed by topic, read as sentences and edited with pickers.

    left    the browser: entries grouped by what they're for, with an English description,
            what they hold (conditions / actions) and how many scenes use them; typing in
            the search box narrows it and Enter opens the first match
    middle  the rule: "True when any one of these ways holds", each way's requirements, its
            other test (condition B), the actions a scene can run, who uses it, and any
            problems -- every line selectable (Up/Down, Alt-hover for the raw form)
    right   the Inspector for the selected line: pick what a requirement checks, how, and
            against what; what an action changes and by how much; add alternatives (OR),
            requirements (AND), ways and actions next to it, or remove it

New requirements and actions start as placeholders that change nothing (an AND-ed "always",
an OR-ed "never", "run entry #0", which is empty), so every step keeps em.bin working.
Every change goes through the document: undoable, counted as unsaved, and checked
(rf4s_modkit.emtext.problems) -- Save refuses an em.bin with errors. The words come from
emtext (English labels, value names, sentences)."""
from __future__ import annotations

import re
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, simpledialog, ttk

import guiutil
from guiutil import FilterCombo, Paned, ScrollFrame, Tip, hint, shortcut_scope
from rf4s_modkit import emscript, emtext, script

from . import catalog


# ---- text-spec helpers (the "Type it…" path and `rf4mod em`) ------------------------ #
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


# ---- rows ---------------------------------------------------------------------------- #
class Row:
    __slots__ = ("segs", "key")

    def __init__(self, segs, key=None):
        self.segs = segs            # [(text, tag or None)]
        self.key = key              # what selecting the row means (see EventManagerWindow)


STREAM_TITLE = {"main": "When a scene runs its actions", "alt": "When a scene runs its alt actions"}
REF_TESTS = [("is true", "cond_a"), ("is false", "not_cond_a"),
             ("passes its other test (B)", "cond_b"), ("fails its other test (B)", "not_cond_b")]
OPS = [("is", "=="), ("is not", "!="), ("is more than", ">"), ("is at least", ">="),
       ("is less than", "<"), ("is at most", "<=")]


def _cap(s):
    return s[:1].upper() + s[1:] if s else s


class EventManagerWindow:
    def __init__(self, app):
        self.app = app
        self.doc = app.doc
        self.win = win = tk.Toplevel(app.frame)
        win.title("Event Manager (em.bin)")
        win.geometry("1320x780")
        self.idx = None                 # the open entry
        self.sel = None                 # the selected row's key
        self.rows = []
        self._key_line = {}
        self._bodies = {}
        self._problems = None
        self._tip = None
        self._hover = None
        self._build_toolbar()
        pane = Paned(win, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.Frame(pane)
        pane.add(left, weight=1, width=300)
        mid = ttk.Frame(pane)
        pane.add(mid, weight=3, width=560)
        right = ttk.Frame(pane)
        pane.add(right, weight=1, width=380)
        self._build_browser(left)
        self._build_rule_view(mid)
        self.insp = ScrollFrame(right, width=370)
        self.insp.pack(fill="both", expand=True)
        self.status = ttk.Label(win, anchor="w", padding=(6, 2), font=("Segoe UI", 8))
        self.status.pack(fill="x", side="bottom")
        self._choices_cache = None
        self.doc.subscribe(self._doc_changed)
        self._counts = {}                    # scene-use counts: filled in right after opening
        self.fill_browser()
        self.show_entry(None)
        win.after(30, self._load_counts)
        # the editor's Ctrl shortcuts work in this window too: its edits share the editor's
        # undo history and Save
        shortcut_scope(win, "CutEdEm%d" % id(self), [
            ("z", lambda e: app.redo() if e.state & 0x0001 else app.undo()),
            ("y", lambda e: app.redo()),
            ("s", lambda e: app.save_all()),
            ("f", lambda e: (self.search_entry.focus_set(), self.search_entry.select_range(0, "end")))],
            home=lambda: self.text)

    # ---- data ------------------------------------------------------------------ #
    @property
    def em(self):
        return self.doc.em

    @property
    def names(self):
        return self.em.names

    def entry(self, idx=None):
        idx = self.idx if idx is None else idx
        em = self.em
        return em.entries[idx] if (idx is not None and 0 <= idx < len(em.entries)) else None

    def label(self, idx):
        """An entry's English description, or its name."""
        e = self.entry(idx)
        if e is None:
            return "#%d" % idx
        return emtext.entry_text(e.name) or e.name or "(unnamed #%d)" % idx

    def problems(self):
        if self._problems is None:
            self._problems = emtext.problems(self.em)
        return self._problems

    def uses(self, idx):
        try:
            return self.app.em_uses(idx)
        except Exception:  # noqa: BLE001 - no rf3.mc loaded: nothing uses it
            return []

    def refs(self, idx):
        return self.em.refs_to(idx)

    def _doc_changed(self, _what=None):
        if not self.win.winfo_exists():
            return
        self._bodies, self._problems = {}, None
        self._counts = self._use_counts()        # incremental: only edited banks are re-scanned
        self.fill_browser(keep=True)
        if self.idx is not None and self.entry() is None:
            self.idx = None
        self.show_entry(self.idx, keep_sel=True)
        self._update_problem_button()

    # ---- toolbar ------------------------------------------------------------------ #
    def _build_toolbar(self):
        bar = ttk.Frame(self.win, padding=(4, 3))
        bar.pack(fill="x")
        self.q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.q, width=34)
        e.pack(side="left")
        self.search_entry = e
        Tip(e, "Search the entries: their description, name, Japanese label and everything they "
               "check or change (a variable like REG_MAIN_SCENARIO, a character, 'rain'). Enter "
               "opens the first match. Ctrl+F jumps here.")
        e.bind("<Return>", lambda _e: self.open_first_match())
        self.q.trace_add("write", lambda *_a: self.fill_browser())
        for text, cmd, tip in (
                ("New entry", self.add_entry, "Add an empty entry at the end (its id is the next number)."),
                ("Copy entry", self.copy_entry, "Add a copy of the open entry at the end."),
                ("Remove entry…", self.remove_entry, "Remove the open entry. Scenes and other entries "
                                                     "that use it are listed first."),
                ("Type it…", self.type_it, "Add a condition or an action by typing it "
                                           "(`Hour >= 6 AND Season == 1`, `REG_X += 2`).")):
            b = ttk.Button(bar, text=text, command=cmd)
            b.pack(side="left", padx=(6, 0))
            Tip(b, tip)
        sv = ttk.Button(bar, text="Save", command=self.app.save_all)
        sv.pack(side="right")
        Tip(sv, "Save every changed file into the game folder (Ctrl+S). em.bin is checked first.")
        self.prob_btn = ttk.Button(bar, text="", command=self.next_problem)
        self.prob_btn.pack(side="right", padx=6)
        Tip(self.prob_btn, "Things in em.bin that break the game (errors: Save refuses them) or "
                           "look wrong (warnings). Click to go to the next one.")
        self._update_problem_button()

    def _update_problem_button(self):
        pr = self.problems()
        err = sum(1 for p in pr if p[0] == "error")
        warn = len(pr) - err
        if not pr:
            self.prob_btn.config(text="✔ No problems")
        else:
            self.prob_btn.config(text="⚠ %s" % ", ".join(
                s for s in ("%d error%s" % (err, "" if err == 1 else "s") if err else "",
                            "%d warning%s" % (warn, "" if warn == 1 else "s") if warn else "") if s))

    def next_problem(self):
        pr = self.problems()
        if not pr:
            self.set_status("em.bin has no problems")
            return
        cur = getattr(self, "_prob_i", -1)
        self._prob_i = (cur + 1) % len(pr)
        level, idx, path, msg = pr[self._prob_i]
        self.open_entry(idx, select=path)
        self.set_status("%s %d of %d: #%d %s" % (level, self._prob_i + 1, len(pr), idx, msg))

    def set_status(self, s):
        self.status.config(text=s)
        self.app.status(s)

    # ---- browser -------------------------------------------------------------------- #
    def _build_browser(self, parent):
        self.tree = ttk.Treeview(parent, show="tree headings", columns=("uses",), selectmode="browse")
        self.tree.heading("#0", text="Entry")
        self.tree.heading("uses", text="used")
        self.tree.column("#0", width=250)
        self.tree.column("uses", width=44, anchor="e", stretch=False)
        sb = ttk.Scrollbar(parent, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("group", font=("Segoe UI", 9, "bold"))
        self.tree.tag_configure("empty", foreground="#999")
        self.tree.tag_configure("err", foreground="#b00020")
        self.tree.bind("<<TreeviewSelect>>", self._tree_pick)
        self._syncing = False
        self._open_groups = {"dates"}

    def _load_counts(self):
        """Fill the browser's 'used' column once the scene-uses index is built (scanning every
        bank takes a few seconds, so the window opens first)."""
        if not self.win.winfo_exists():
            return
        self.set_status("counting scene uses…")
        self.win.update_idletasks()
        self._counts = self._use_counts()
        self.fill_browser(keep=True)
        self.set_status("")

    def _use_counts(self):
        try:
            return self.app.em_use_counts()
        except Exception:  # noqa: BLE001 - no rf3.mc loaded
            return {}

    def body(self, e):
        """Everything searchable about an entry, lower-cased."""
        b = self._bodies.get(e.idx)
        if b is None:
            names = self.names
            parts = [e.name or "", e.jp or "", emtext.entry_text(e.name), "#%d" % e.idx,
                     self.em.format_entry(e)]
            for slots in (e.cond_a, e.cond_b):
                for xs in slots or ():
                    parts += [emtext.expr_text(names, x, self.label) for x in xs]
            for acts in (e.actions, e.alt_actions):
                parts += [emtext.action_text(names, a, self.label) for a in acts or ()]
            b = self._bodies[e.idx] = "\n".join(parts).lower()
        return b

    def matches(self):
        words = self.q.get().lower().split()
        out = []
        for e in self.em.entries:
            if not words or all(w in self.body(e) for w in words):
                out.append(e)
        return out

    def fill_browser(self, keep=False):
        t = self.tree
        for g in t.get_children():
            if t.item(g, "open"):
                self._open_groups.add(g[2:])
            else:
                self._open_groups.discard(g[2:])
        t.delete(*t.get_children())
        counts = getattr(self, "_counts", None)
        if counts is None:
            counts = self._counts = self._use_counts()
        bad = {p[1] for p in self.problems() if p[0] == "error"}
        shown = self.matches()
        searching = bool(self.q.get().strip())
        by_group = {}
        for e in shown:
            by_group.setdefault(emtext.entry_group(e.name), []).append(e)
        for key, title, _test in emtext.GROUPS:
            es = by_group.get(key)
            if not es:
                continue
            gid = t.insert("", "end", iid="g:" + key, text="%s  (%d)" % (title, len(es)), tags=("group",),
                           open=searching or key in self._open_groups)
            for e in es:
                marks = ("✔" if (e.cond_a or e.cond_b) else "") + ("▶" if (e.actions or e.alt_actions) else "")
                n = counts.get(e.idx, 0)
                tags = ("err",) if e.idx in bad else (("empty",) if not (e.cond_a or e.cond_b or e.actions
                                                                          or e.alt_actions) else ())
                t.insert(gid, "end", iid="e:%d" % e.idx, values=(n or "",), tags=tags,
                         text="#%d %s %s" % (e.idx, self.label(e.idx), marks))
        self.win.title("Event Manager (em.bin) — %d entries%s" % (
            len(self.em.entries), (" — %d match%s" % (len(shown), "" if len(shown) == 1 else "es"))
            if searching else ""))
        if keep and self.idx is not None:
            self._reveal(self.idx)

    def _reveal(self, idx):
        iid = "e:%d" % idx
        t = self.tree
        if not t.exists(iid):
            return
        t.item(t.parent(iid), open=True)
        self._syncing = True
        try:
            t.selection_set(iid)
            t.see(iid)
        finally:
            self.win.after_idle(lambda: setattr(self, "_syncing", False))

    def _tree_pick(self, _e=None):
        if self._syncing:
            return
        s = self.tree.selection()
        if s and s[0].startswith("e:"):
            self.show_entry(int(s[0][2:]))

    def open_first_match(self):
        m = self.matches()
        if m:
            self.open_entry(m[0].idx)
            self.set_status("%d entr%s match “%s”" % (len(m), "y" if len(m) == 1 else "ies", self.q.get()))
        else:
            self.set_status("nothing matches “%s”" % self.q.get())

    def open_entry(self, idx, select=None):
        """Open entry `idx` (selected in the browser too) and optionally select a row."""
        if self.q.get().strip() and not any(e.idx == idx for e in self.matches()):
            self.q.set("")
        self._reveal(idx)
        self.show_entry(idx, select=select)

    def select_idx(self, idx):
        if self.entry(idx) is None:
            return False
        self.open_entry(idx)
        return True

    # ---- rule view ------------------------------------------------------------------ #
    def _build_rule_view(self, parent):
        self.text = t = tk.Text(parent, wrap="word", font=("Segoe UI", 10), cursor="arrow",
                                padx=10, pady=8, relief="flat", spacing1=1, spacing3=1)
        sb = ttk.Scrollbar(parent, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        t.config(state="disabled")
        t.tag_configure("h1", font=("Segoe UI", 13, "bold"))
        t.tag_configure("desc", font=("Segoe UI", 10), foreground="#333")
        t.tag_configure("dim", foreground="#888", font=("Segoe UI", 9))
        t.tag_configure("sec", font=("Segoe UI", 10, "bold"), foreground="#0d5f8f")
        t.tag_configure("way", font=("Segoe UI", 10, "bold"))
        t.tag_configure("req", font=("Segoe UI", 10))
        t.tag_configure("or", foreground="#7a5a00", font=("Segoe UI", 9, "italic"))
        t.tag_configure("act", font=("Segoe UI", 10), foreground="#1d6b2f")
        t.tag_configure("link", foreground="#0d5f8f", underline=True)
        t.tag_configure("warn", foreground="#b36200")
        t.tag_configure("err", foreground="#b00020")
        t.tag_configure("selrow", background="#dbe8f6")
        t.bind("<Button-1>", self._click)
        t.bind("<Double-Button-1>", self._double)
        for seq in ("<B1-Motion>", "<Shift-Button-1>", "<Triple-Button-1>", "<Control-a>"):
            t.bind(seq, lambda _e: "break")
        t.bind("<Up>", lambda _e: self.move(-1))
        t.bind("<Down>", lambda _e: self.move(1))
        t.bind("<Return>", lambda _e: (self._double(None), "break")[1])
        t.bind("<Delete>", lambda _e: (self.remove_selected(), "break")[1])
        t.bind("<Motion>", self._motion)
        t.bind("<Leave>", lambda _e: self.hide_tip())
        alt = 0x20000 if sys.platform == "win32" else 0x0008
        self._alt_mask = alt
        for seq in ("<KeyPress-Alt_L>", "<KeyPress-Alt_R>"):
            self.win.bind(seq, lambda _e: (self._alt(True), "break")[1], add="+")
        for seq in ("<KeyRelease-Alt_L>", "<KeyRelease-Alt_R>"):
            self.win.bind(seq, lambda _e: (self._alt(False), "break")[1], add="+")

    def build_rows(self, e):
        names, em = self.names, self.em
        rows = []
        if e is None:
            rows.append(Row([("Pick an entry on the left.", "desc")]))
            rows.append(Row([("", None)]))
            rows.append(Row([("Every entry is a rule the game asks “is this true right now?” "
                              "— to decide which dialogue plays, whether a shop is open, which "
                              "event fires today. Some also have actions a scene can run.", "dim")]))
            return rows
        probs = {}
        for level, pidx, path, msg in self.problems():
            if pidx == e.idx:
                probs.setdefault(path, []).append((level, msg))

        def mark(path):
            ps = probs.get(path)
            if not ps:
                return []
            lvl = "err" if any(p[0] == "error" for p in ps) else "warn"
            return [("   ⚠ " + "; ".join(m for _l, m in ps), lvl)]

        rows.append(Row([("#%d  " % e.idx, "dim"), (self.label(e.idx), "h1")], ("entry",)))
        rows.append(Row([(e.name or "(unnamed)", "dim"), (("   " + e.jp) if e.jp else "", "dim")], ("entry",)))
        rows.append(Row([("", None)]))
        for which, slots, title in (("a", e.cond_a, None), ("b", e.cond_b, "Its other test (condition B)")):
            if which == "b" and not slots:
                continue
            if which == "a":
                if not slots and (e.actions or e.alt_actions):
                    rows.append(Row([("No condition — scenes only run its actions (asked whether it's "
                                      "true, it answers false)", "dim")], ("sec", "a")))
                elif not slots:
                    rows.append(Row([("✖ Never true — it has no condition", "sec")], ("sec", "a")))
                elif len(slots) == 1:
                    rows.append(Row([("✔ True when:", "sec")], ("sec", "a")))
                else:
                    rows.append(Row([("✔ True when any one of these ways holds:", "sec")], ("sec", "a")))
            else:
                rows.append(Row([("", None)]))
                rows.append(Row([("✔ %s — %s:" % (title, "any one of these ways" if len(slots) > 1
                                                           else "true when"), "sec")], ("sec", "b")))
            for si, xs in enumerate(slots or ()):
                if len(slots) > 1:
                    rows.append(Row([("   Way %d" % (si + 1), "way"),
                                     ("  — all of these:" if len(emtext.groups_of(xs)) > 1 else "", "dim")],
                                    ("slot", which, si)))
                ind = "      " if len(slots) > 1 else "   "
                for grp in emtext.groups_of(xs):
                    if len(grp) == 1:
                        xi, x = grp[0]
                        rows.append(Row([(ind + "• ", "dim"), (_cap(emtext.expr_text(names, x, self.label)),
                                                                      "link" if x.kind.endswith(("cond_a", "cond_b"))
                                                                      else "req")]
                                        + mark(("expr", which, si, xi)), ("expr", which, si, xi)))
                    else:
                        rows.append(Row([(ind + "• one of:", "or")], ("expr", which, si, grp[0][0])))
                        for xi, x in grp:
                            rows.append(Row([(ind + "      ◦ ", "dim"),
                                             (_cap(emtext.expr_text(names, x, self.label)),
                                              "link" if x.kind.endswith(("cond_a", "cond_b")) else "req")]
                                            + mark(("expr", which, si, xi)), ("expr", which, si, xi)))
        for stream, acts in (("main", e.actions), ("alt", e.alt_actions)):
            if not acts:
                continue
            rows.append(Row([("", None)]))
            rows.append(Row([("▶ %s:" % STREAM_TITLE[stream], "sec")], ("sec", stream)))
            for ai, a in enumerate(acts):
                rows.append(Row([("   %d. " % (ai + 1), "dim"),
                                 (_cap(emtext.action_text(names, a, self.label)), "link" if a.name == "CALL" else "act")]
                                + mark(("act", stream, ai)), ("act", stream, ai)))
        # who uses it
        uses, refs = self.uses(e.idx), self.refs(e.idx)
        dyn = []
        try:
            dyn = self.app.em_dynamic_uses()
        except Exception:  # noqa: BLE001
            pass
        rows.append(Row([("", None)]))
        if not uses and not refs and not dyn:
            rows.append(Row([("↪ Nothing in rf3.mc or em.bin uses this entry (the engine may still "
                              "ask for it by number).", "dim")]))
        if uses:
            rows.append(Row([("↪ Used by %d scene statement%s (double-click to open):"
                              % (len(uses), "" if len(uses) == 1 else "s"), "sec")]))
            for pos, entry, pc, st in uses[:60]:
                bank = self.doc.container.banks[pos]
                rows.append(Row([("   ", None), (catalog.bank_title(bank)[:44], "link"),
                                 ("  scene @0x%04x · %s" % (entry, script.opcode_mnemonic(st.op)), "dim")],
                                ("use", pos, entry, pc)))
            if len(uses) > 60:
                rows.append(Row([("   … and %d more" % (len(uses) - 60), "dim")]))
        if dyn:
            rows.append(Row([("↪ %d scene statement%s pick%s the entry at run time (from a variable), so "
                              "%s may use this one too:" % (len(dyn), "" if len(dyn) == 1 else "s",
                                                             "s" if len(dyn) == 1 else "",
                                                             "it" if len(dyn) == 1 else "they"), "sec")]))
            for pos, entry, pc, st in dyn[:30]:
                bank = self.doc.container.banks[pos]
                rows.append(Row([("   ", None), (catalog.bank_title(bank)[:44], "link"),
                                 ("  scene @0x%04x · %s" % (entry, script.opcode_mnemonic(st.op)), "dim")],
                                ("use", pos, entry, pc)))
        if refs:
            rows.append(Row([("↪ Used by %d other entr%s:" % (len(refs), "y" if len(refs) == 1 else "ies"), "sec")]))
            for re_, what in refs:
                rows.append(Row([("   #%d " % re_.idx, "dim"), (self.label(re_.idx), "link"), ("  (%s)" % what, "dim")],
                                ("ref", re_.idx)))
        whole = probs.get(None)
        if whole:
            rows.append(Row([("", None)]))
            for level, msg in whole:
                rows.append(Row([("⚠ " + msg, "err" if level == "error" else "warn")]))
        return rows

    def show_entry(self, idx, keep_sel=False, select=None):
        self.hide_tip()
        changed = idx != self.idx
        self.idx = idx
        e = self.entry()
        self.rows = self.build_rows(e)
        t = self.text
        y = t.yview()[0]
        t.config(state="normal")
        t.delete("1.0", "end")
        self._key_line = {}
        for n, row in enumerate(self.rows, 1):
            for s, tag in row.segs:
                t.insert("end", s, tag or ())
            t.insert("end", "\n")
            if row.key is not None and row.key not in self._key_line:
                self._key_line[row.key] = n
        t.config(state="disabled")
        if keep_sel and not changed:
            t.yview_moveto(y)
        if select is not None and select in self._key_line:
            self.select(select)
        elif keep_sel and not changed and self.sel in self._key_line:
            self.select(self.sel, see=False)
        else:
            self.select(("entry",) if e is not None else None)

    def _line_at(self, ev):
        return int(self.text.index("@%d,%d" % (ev.x, ev.y)).split(".")[0])

    def _click(self, ev):
        self.text.focus_set()
        ln = self._line_at(ev)
        row = self.rows[ln - 1] if 0 < ln <= len(self.rows) else None
        if row is not None and row.key is not None:
            self.select(row.key)
        return "break"

    def _double(self, ev):
        if ev is not None:
            self._click(ev)
        k = self.sel
        if not k:
            return "break"
        if k[0] == "use":
            self.open_use(k)
        elif k[0] == "ref":
            self.open_entry(k[1])
        elif k[0] in ("expr", "act"):
            ref = self._ref_of(k)
            if ref is not None:
                self.open_entry(ref)
            else:
                self.focus_form()
        return "break"

    def _ref_of(self, key):
        """The entry a requirement / CALL action points at, or None."""
        e = self.entry()
        try:
            if key[0] == "expr":
                x = ((e.cond_a if key[1] == "a" else e.cond_b) or [])[key[2]][key[3]]
                return x.ref if x.kind in ("cond_a", "not_cond_a", "cond_b", "not_cond_b") else None
            if key[0] == "act":
                a = (e.actions if key[1] == "main" else e.alt_actions)[key[2]]
                return a.entry if a.name == "CALL" else None
        except (IndexError, TypeError, AttributeError):
            return None
        return None

    def select(self, key, see=True):
        self.sel = key
        t = self.text
        t.tag_remove("selrow", "1.0", "end")
        ln = self._key_line.get(key)
        if ln is not None:
            t.tag_add("selrow", "%d.0" % ln, "%d.0" % (ln + 1))
            if see:
                t.see("%d.0" % ln)
        self.show_form(key)

    def move(self, delta):
        keys = []
        for r in self.rows:
            if r.key is not None and r.key not in keys:
                keys.append(r.key)
        if not keys:
            return "break"
        i = keys.index(self.sel) if self.sel in keys else (-1 if delta > 0 else len(keys))
        self.select(keys[max(0, min(len(keys) - 1, i + delta))])
        return "break"

    # ---- Alt-hover: the raw form and the details of what a line checks ---------------- #
    def _motion(self, ev):
        ln = self._line_at(ev)
        row = self.rows[ln - 1] if 0 < ln <= len(self.rows) else None
        self._hover = (row, ev.x_root + 16, ev.y_root + 18) if (row and row.key) else None
        if ev.state & self._alt_mask and self._hover:
            self._show_hover()
        else:
            self.hide_tip()

    def _alt(self, down):
        if down and self._hover:
            self._show_hover()
        elif not down:
            self.hide_tip()

    def explain(self, key):
        """What a row says, precisely: the raw em.bin form and what each side is."""
        e = self.entry()
        names = self.names
        if e is None or key is None:
            return ""
        if key[0] == "entry":
            return "#%d %s\n%s\n%s" % (e.idx, e.name or "(unnamed)", e.jp or "", emtext.entry_text(e.name))
        out = []

        def about(o, what):
            if o is None:
                return
            if o.kind == "query":
                lab, kind, note = emtext.query_info(names, o.value)
                en, jp = (names.query_names[o.value] if 0 <= o.value < len(names.query_names) else ("?", ""))
                out.append("%s: game query %d %s (%s)%s" % (what, o.value, en, jp, " — " + note if note else ""))
            elif o.kind == "flag":
                v = names.flag_at(o.value)
                out.append("%s: variable %s — bit %d, %d bit%s%s" % (
                    what, o.pretty(names), o.value, o.width, "" if o.width == 1 else "s",
                    ("  " + v.jp_name) if v is not None and getattr(v, "jp_name", "") else ""))
            elif o.kind in ("lit", "slit"):
                out.append("%s: the number %s" % (what, o.pretty(names)))
        try:
            if key[0] == "expr":
                x = ((e.cond_a if key[1] == "a" else e.cond_b) or [])[key[2]][key[3]]
                out.append("em.bin: %s%s" % (x.pretty(names), "   (OR with the next)" if x.or_next else ""))
                if x.kind == "cmp":
                    about(x.op1, "left")
                    about(x.op2, "right")
                elif x.kind not in ("true", "false"):
                    out.append("entry #%d %s" % (x.ref, self.label(x.ref)))
            elif key[0] == "act":
                a = (e.actions if key[1] == "main" else e.alt_actions)[key[2]]
                out.append("em.bin: %s   (%s)" % (a.pretty(names), emscript.OP_HELP.get(a.name, "")))
                if a.name != "CALL":
                    about(a.target, "changes")
                    about(a.value, "by")
            elif key[0] == "slot":
                out.append("One way the entry can be true: every requirement listed under it must hold.")
            elif key[0] == "sec":
                out.append({"a": "Condition A: true when any one way holds (CondScript_EvalEntry).",
                            "b": "Condition B: a second test scenes can ask for ('is B true').",
                            "main": "Run by rf3.mc's DispatchCondScriptEntry (op 373).",
                            "alt": "Run by rf3.mc's CondScriptDispatchAltAction (op 374)."}[key[1]])
            elif key[0] == "use":
                out.append("Double-click to open this scene at the statement.")
            elif key[0] == "ref":
                out.append("Double-click to open entry #%d." % key[1])
        except (IndexError, KeyError, TypeError):
            return ""
        return "\n".join(out)

    def _show_hover(self):
        row, x, y = self._hover
        text = self.explain(row.key)
        if not text:
            return
        if self._tip is None:
            self._tip = tk.Toplevel(self.win)
            self._tip.wm_overrideredirect(True)
            if sys.platform == "win32":
                try:
                    self._tip.wm_attributes("-disabled", True)
                except tk.TclError:
                    pass
            lbl = tk.Label(self._tip, justify="left", anchor="w", bg="#1b1b22", fg="#e6e6ee",
                           font=("Segoe UI", 9), relief="solid", bd=1, padx=8, pady=6)
            lbl.config(wraplength=min(tkfont.Font(font=lbl["font"]).measure("m" * 55),
                                           guiutil.tip_wraplength(lbl, x, y, 10 ** 6)))
            lbl.pack()
            self._tip_lbl = lbl
        self._tip_lbl.config(text=text)
        guiutil.place_popup(self._tip, x, y)   # kept on the monitor
        had = self.win.focus_get()
        self._tip.deiconify()
        if had is not None and self.win.focus_get() is not had:
            had.focus_set()

    def hide_tip(self):
        if self._tip is not None:
            self._tip.withdraw()

    # ---- the Inspector ---------------------------------------------------------------- #
    def _clear_form(self):
        for w in self.insp.body.winfo_children():
            w.destroy()
        self.insp.to_top()
        self._primary = None

    def focus_form(self):
        if getattr(self, "_primary", None) is not None:
            self._primary.focus_set()

    def _title(self, text, sub=""):
        ttk.Label(self.insp.body, text=text, font=("Segoe UI", 11, "bold"), wraplength=340,
                  justify="left").pack(anchor="w", padx=6, pady=(6, 0))
        if sub:
            ttk.Label(self.insp.body, text=sub, foreground="#666", font=("Segoe UI", 8), wraplength=340,
                      justify="left").pack(anchor="w", padx=6)

    def _buttons(self, parent, specs):
        f = ttk.Frame(parent)
        f.pack(fill="x", padx=6, pady=(6, 2))
        for i, (text, cmd, tip) in enumerate(specs):
            b = ttk.Button(f, text=text, command=cmd)
            b.grid(row=i // 2, column=i % 2, sticky="we", padx=2, pady=2)
            Tip(b, tip)
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)
        return f

    def _row_problems(self, key):
        e = self.entry()
        if e is None:
            return
        for level, pidx, path, msg in self.problems():
            if pidx == e.idx and path == key[:4]:
                ttk.Label(self.insp.body, text="⚠ " + msg, wraplength=340, justify="left",
                          foreground="#b00020" if level == "error" else "#b36200").pack(anchor="w", padx=8, pady=(4, 0))

    def show_form(self, key):
        self._clear_form()
        e = self.entry()
        b = self.insp.body
        try:
            if e is None:
                self._title("Event Manager", "em.bin — %d entries" % len(self.em.entries))
                hint(b, "Pick an entry on the left, or search for what it's about. Each entry is a "
                        "rule: its condition says when it is true; some also have actions scenes run. "
                        "Hold Alt over a line for its exact form.", wrap=340).pack(anchor="w", padx=6, pady=4)
            elif key is None or key[0] == "entry":
                self._entry_form(e)
            elif key[0] == "sec":
                self._section_form(e, key[1])
            elif key[0] == "slot":
                self._slot_form(e, key[1], key[2])
            elif key[0] == "expr":
                self._expr_form(e, key)
            elif key[0] == "act":
                self._act_form(e, key)
            elif key[0] == "use":
                self._use_form(key)
            elif key[0] == "ref":
                self._title("Entry #%d" % key[1], self.label(key[1]))
                self._buttons(b, [("Open entry #%d" % key[1], lambda: self.open_entry(key[1]),
                                   "Open the entry that uses this one.")])
        except (IndexError, TypeError):
            self._title("(this line changed)")
        self.insp.bind_wheel_tree()

    def _entry_form(self, e):
        b = self.insp.body
        self._title("#%d %s" % (e.idx, self.label(e.idx)),
                    "%s%s" % (e.name or "(unnamed)", ("  ·  " + e.jp) if e.jp else ""))
        ways = len(e.cond_a or ())
        hint(b, ("True in %d way%s. " % (ways, "" if ways == 1 else "s") if ways else
                 "Never true: it has no condition yet. ")
             + ("%d action%s. " % (len(e.actions), "" if len(e.actions) == 1 else "s") if e.actions else "")
             + ("%d alt action%s. " % (len(e.alt_actions), "" if len(e.alt_actions) == 1 else "s")
                if e.alt_actions else "")
             + ("It also has its other test (condition B). " if e.cond_b else ""), wrap=340).pack(anchor="w", padx=6, pady=4)
        self._buttons(b, [
            ("Add a way it can be true", lambda: self.add_way("a"),
             "Add another way this entry can be true (it is true when ANY way holds). It starts as "
             "'never', so nothing changes until you pick what it checks."),
            ("Add an action", lambda: self.add_action_to("main"),
             "Add an action scenes run with DispatchCondScriptEntry (op 373). It starts as 'run entry "
             "#0', which does nothing, until you pick what it changes."),
            ("Add an alt action", lambda: self.add_action_to("alt"),
             "Add an action to the alt stream (run by CondScriptDispatchAltAction, op 374)."),
            ("Add its other test (B)", lambda: self.add_way("b"),
             "Add a way for condition B, the second test scenes can ask for."),
        ])

    def _section_form(self, e, which):
        b = self.insp.body
        if which in ("a", "b"):
            self._title("Condition %s" % which.upper(), "True when ANY one of its ways holds; a way holds when "
                        "ALL of its requirements do.")
            self._buttons(b, [("Add a way", lambda: self.add_way(which),
                               "Add another way (it starts as 'never', which changes nothing).")])
        else:
            self._title(STREAM_TITLE[which], "Run in order, top to bottom.")
            self._buttons(b, [("Add an action", lambda: self.add_action_to(which),
                               "Add an action at the end (it starts as 'run entry #0', which does nothing).")])

    def _slot_form(self, e, which, si):
        b = self.insp.body
        slots = (e.cond_a if which == "a" else e.cond_b) or []
        xs = slots[si]
        self._title("Way %d of %d" % (si + 1, len(slots)),
                    "Condition %s holds this way when all of its requirements hold." % which.upper())
        for grp in emtext.groups_of(xs):
            ttk.Label(b, text="• " + " OR ".join(_cap(emtext.expr_text(self.names, x, self.label)) for _i, x in grp),
                      wraplength=330, justify="left").pack(anchor="w", padx=10)
        self._buttons(b, [
            ("Add a requirement", lambda: self.add_requirement(which, si, len(xs) - 1, "and"),
             "Add another requirement to this way (it starts as 'always', which changes nothing)."),
            ("Remove this way", lambda: self.remove_way(which, si), "Remove this way and all its requirements."),
        ])

    def _use_form(self, key):
        _k, pos, entry, pc = key
        bank = self.doc.container.banks[pos]
        self._title("Used by a scene", "%s · scene @0x%04x · statement @0x%04x"
                    % (catalog.bank_title(bank), entry, pc))
        self._buttons(self.insp.body, [("Open the scene", lambda: self.open_use(key),
                                        "Show this statement in the cutscene editor.")])

    def open_use(self, key):
        _k, pos, entry, pc = key
        self.app.open_scene(pos, entry, focus_pc=pc)
        try:
            self.app.frame.winfo_toplevel().lift()
        except tk.TclError:
            pass

    # -- choice lists ------------------------------------------------------------------- #
    def choices(self):
        """Picker lists: (operands [queries + variables], variables only, entries)."""
        if self._choices_cache is None or self._choices_cache[0] is not self.em:
            names = self.names
            qs = ["%s  [q%d %s]" % (emtext.query_info(names, i)[0], i, en)
                  for i, (en, _jp) in enumerate(names.query_names)]
            vs = [emtext.variable_label(v) for v in names.flags.variables]
            vs += [text for text, _tok in emtext.zone2_choices()]     # the recovered zone-2 flags
            es =["#%d  %s — %s" % (e.idx, self.label(e.idx), e.name or "") for e in self.em.entries]
            self._choices_cache = (self.em, qs + vs, vs, es)
        return self._choices_cache[1:]

    def operand_choice(self, o):
        """The picker text for an existing operand."""
        names = self.names
        if o is None:
            return ""
        if o.kind == "query":
            en = names.query_name(o.value) or ""
            return "%s  [q%d %s]" % (emtext.query_info(names, o.value)[0], o.value, en)
        if o.kind == "flag":
            v = names.flag_at(o.value)
            if v is not None and v.bit_offset == o.value and v.bit_width == o.width:
                return emtext.variable_label(v)
            rel = emtext.zone2_rel(o)
            if rel is not None and o.width == 1:
                tag = "[z%d]" % rel
                hit = next((text for text, _tok in emtext.zone2_choices() if text.endswith(tag)), None)
                if hit:
                    return hit
            return "flag@%d/%d" % (o.value, o.width)            # an unnamed bit, typed form
        return o.pretty(names)

    def token_of(self, text):
        """What a picker's text means, as an em.bin operand token."""
        t = (text or "").strip()
        m = re.search(r"\[z(\d+)\]$", t)                         # a zone-2 flag
        if m:
            from rf4s_modkit.emflags import ZONE2_BASE
            return "flag@%d/1" % (ZONE2_BASE + int(m.group(1)))
        m = re.search(r"\[q(\d+) [^\]]*\]$", t)
        if m:
            return "q:%s" % m.group(1)
        m = re.fullmatch(r".*\((-?(?:0x[0-9a-fA-F]+|\d+))\)", t)
        if m:
            return m.group(1)
        return t.split("  — ")[0].split()[0] if t else ""

    def value_choices(self, kind):
        vals = emtext.value_names(kind) if kind else None
        if kind == "map":
            from rf4s_modkit.map_names import map_count, map_name
            return ["%s (%d)" % (map_name(i), i) for i in range(map_count()) if map_name(i)]
        return ["%s (%d)" % (nm, v) for v, nm in sorted(vals.items())] if vals else []

    def value_display(self, o, kind):
        if o is None:
            return ""
        if o.kind in ("lit", "slit"):
            v = int(o.pretty(self.names))
            nm = emtext.value_text(kind, v)
            return "%s (%d)" % (nm, v) if nm else str(v)
        return self.operand_choice(o)

    def entry_choice(self, idx):
        e = self.entry(idx)
        return "#%d  %s — %s" % (idx, self.label(idx), (e.name if e else "") or "")

    @staticmethod
    def entry_of(text):
        m = re.match(r"\s*#?(\d+)", text or "")
        return int(m.group(1)) if m else None

    def _picker(self, parent, row, label, values, current, on_pick, tip, width=38):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 4), pady=2)
        done = {"v": False}

        def pick(text):
            if not done["v"] and text.strip() and text != current:
                done["v"] = True
                on_pick(text)
        fc = FilterCombo(parent, values, on_pick=pick, width=width)
        fc.var.set(current)
        fc.grid(row=row, column=1, sticky="we", pady=2)
        fc.bind("<FocusOut>", lambda _e: pick(fc.var.get()), add="+")
        fc._commit = lambda: pick(fc.var.get())       # Ctrl+S / undo apply a typed value first
        Tip(fc, tip)
        return fc

    def _combo(self, parent, row, label, values, current, on_pick, tip, width=24):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 4), pady=2)
        cb = ttk.Combobox(parent, values=values, state="readonly", width=width)
        cb.set(current)
        cb.grid(row=row, column=1, sticky="w", pady=2)
        cb.bind("<<ComboboxSelected>>", lambda _e: on_pick(cb.get()))
        Tip(cb, tip)
        return cb

    # -- requirement form ---------------------------------------------------------------- #
    def _expr(self, e, key):
        return ((e.cond_a if key[1] == "a" else e.cond_b) or [])[key[2]][key[3]]

    def _expr_form(self, e, key):
        b = self.insp.body
        x = self._expr(e, key)
        _k, which, si, xi = key
        self._title("Requirement", _cap(emtext.expr_text(self.names, x, self.label)))
        self._row_problems(key)
        kind = ("value" if x.kind == "cmp" else "entry" if x.kind not in ("true", "false") else "fixed")
        mode = self._mode_var = tk.StringVar(master=self.win, value=kind)   # kept: Tk forgets GC'd vars
        mf = ttk.Frame(b)
        mf.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Label(mf, text="It checks").pack(side="left")
        for val, text, tip in (("value", "a value", "Compare a game value or a variable with a number, "
                                "or two of them with each other."),
                               ("entry", "another entry", "Ask whether another entry is true (or passes "
                                "its other test)."),
                               ("fixed", "nothing", "Always true, or never true.")):
            rb = ttk.Radiobutton(mf, text=text, value=val, variable=mode,
                                 command=lambda v=val: self._switch_expr(key, v))
            rb.pack(side="left", padx=(6, 0))
            Tip(rb, tip)
        g = ttk.Frame(b)
        g.pack(fill="x", padx=6, pady=4)
        g.columnconfigure(1, weight=1)
        operands, _vs, entries = self.choices()
        if x.kind == "cmp":
            a, bb, op = x.op1, x.op2, x.cmp
            if a is not None and bb is not None and a.kind in ("lit", "slit") and bb.kind not in ("lit", "slit"):
                a, bb, op = bb, a, {">": "<", ">=": "<="}.get(op, op)     # show "Hour < 12", not "12 > Hour"
            ka = emtext.operand_kind(self.names, a)
            st = {"left": self.operand_choice(a), "op": op, "right": self.value_display(bb, ka)}
            st["_orig"] = {"left": (st["left"], a), "right": (st["right"], bb)}

            def apply(**chg):
                st.update(chg)
                self._set_cmp(key, st)
            self._primary = self._picker(g, 0, "What", operands, st["left"], lambda t: apply(left=t),
                                         "The game value or variable to check. Type to search: 'love kiel', "
                                         "'hour', 'REG_MAIN'.")
            self._combo(g, 1, "How", [w for w, _o in OPS], next((w for w, o in OPS if o == op), op),
                        lambda w: apply(op=dict(OPS)[w]), "How it compares.")
            vals = self.value_choices(ka) or []
            self._picker(g, 2, "Against", vals + operands, st["right"], lambda t: apply(right=t),
                         "A number, a named value%s, or another game value / variable."
                         % (" (%s)" % ", ".join(vals[:4]) if vals else ""))
            if ka == "bool":
                hint(b, "On/off values: 1 = yes / on, 0 = no / off.", wrap=340).pack(anchor="w", padx=8)
        elif x.kind in ("cond_a", "not_cond_a", "cond_b", "not_cond_b"):
            st = {"ref": x.ref, "test": x.kind}

            def apply_ref(**chg):
                st.update(chg)
                self._set_ref(key, st)
            self._primary = self._picker(g, 0, "Entry", entries, self.entry_choice(x.ref),
                                         lambda t: apply_ref(ref=self.entry_of(t)),
                                         "The entry to ask. Type to search its description or name.")
            self._combo(g, 1, "Must", [w for w, _k in REF_TESTS], next(w for w, k in REF_TESTS if k == x.kind),
                        lambda w: apply_ref(test=dict(REF_TESTS)[w]),
                        "True / false = its condition A; the other test = its condition B.")
            ttk.Button(g, text="Open that entry", command=lambda: self.open_entry(x.ref)).grid(
                row=2, column=1, sticky="w", pady=2)
            Tip(g.winfo_children()[-1], "Open the entry this requirement asks about.")
        else:
            self._combo(g, 0, "It is", ["always true", "never true"],
                        "always true" if x.kind == "true" else "never true",
                        lambda w: self._replace_expr(key, "TRUE" if w.startswith("always") else "FALSE"),
                        "'Always' AND-ed changes nothing; 'never' OR-ed changes nothing.")
        self._buttons(b, [
            ("Add an alternative (OR)", lambda: self.add_requirement(which, si, xi, "or"),
             "Add another requirement either of which is enough (starts as 'never', which changes nothing)."),
            ("Add a requirement (AND)", lambda: self.add_requirement(which, si, xi, "and"),
             "Add another requirement that must also hold (starts as 'always', which changes nothing)."),
            ("Remove", self.remove_selected, "Remove this requirement (Del)."),
            ("Remove the whole way", lambda: self.remove_way(which, si), "Remove the way this requirement is in."),
        ])

    def _switch_expr(self, key, mode):
        text = {"value": "Hour >= 0", "entry": "condA(#0)", "fixed": "TRUE"}[mode]
        self._replace_expr(key, text, "What it checks changed")

    def _operand(self, text):
        return self.em.make_operand(self.token_of(text))

    def _keep_or_parse(self, st, field):
        shown, obj = st.get("_orig", {}).get(field, (None, None))
        return obj if (obj is not None and st[field] == shown) else self._operand(st[field])

    def _set_cmp(self, key, st):
        try:
            o1, o2 = self._keep_or_parse(st, "left"), self._keep_or_parse(st, "right")
        except ValueError as ex:
            messagebox.showerror("Requirement", str(ex), parent=self.win)
            return self.show_form(key)
        op = st["op"]
        if op in ("<", "<="):                               # the VM has no < / <=: swap the sides
            o1, o2, op = o2, o1, {"<": ">", "<=": ">="}[op]
        em = self.em
        x = emscript.Expr(em._OP_NIBBLE[op] | (em._TYPE_BITS[o1.kind] << 2) | em._TYPE_BITS[o2.kind],
                          "cmp", cmp=op, op1=o1, op2=o2)
        return self._edit("Change requirement of em.bin #%d" % self.idx,
                          lambda: self.em.replace_expr(self.idx, key[1], key[2], key[3], x), select=key)

    def _set_ref(self, key, st):
        if st["ref"] is None:
            return
        neg = "!" if st["test"].startswith("not_") else ""
        var = "A" if st["test"].endswith("_a") else "B"
        self._replace_expr(key, "%scond%s(#%d)" % (neg, var, st["ref"]))

    def _replace_expr(self, key, text, label=None):
        return self._edit(label or "Change requirement of em.bin #%d" % self.idx,
                          lambda: self.em.replace_expr(self.idx, key[1], key[2], key[3], self.em.make_expr(text)),
                          select=key)

    # -- action form ----------------------------------------------------------------------- #
    def _act(self, e, key):
        return (e.actions if key[1] == "main" else e.alt_actions)[key[2]]

    def _act_form(self, e, key):
        b = self.insp.body
        a = self._act(e, key)
        _k, stream, ai = key
        self._title("Action %d" % (ai + 1), _cap(emtext.action_text(self.names, a, self.label)))
        self._row_problems(key)
        mode = self._mode_var = tk.StringVar(master=self.win, value="call" if a.name == "CALL" else "change")
        mf = ttk.Frame(b)
        mf.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Label(mf, text="It").pack(side="left")
        for val, text, tip in (("change", "changes a variable", "Set, add to, subtract from … a variable."),
                               ("call", "runs another entry", "Run another entry's actions of the same "
                                "kind (actions → actions, alt → alt).")):
            rb = ttk.Radiobutton(mf, text=text, value=val, variable=mode,
                                 command=lambda v=val: self._switch_act(key, v))
            rb.pack(side="left", padx=(6, 0))
            Tip(rb, tip)
        g = ttk.Frame(b)
        g.pack(fill="x", padx=6, pady=4)
        g.columnconfigure(1, weight=1)
        operands, variables, entries = self.choices()
        if a.name == "CALL":
            self._primary = self._picker(g, 0, "Entry", entries, self.entry_choice(a.entry),
                                         lambda t: self._set_call(key, self.entry_of(t)),
                                         "The entry whose actions run. Type to search.")
            ttk.Button(g, text="Open that entry", command=lambda: self.open_entry(a.entry)).grid(
                row=1, column=1, sticky="w", pady=2)
            Tip(g.winfo_children()[-1], "Open the entry this action runs.")
        else:
            kt = emtext.operand_kind(self.names, a.target)
            st = {"target": self.operand_choice(a.target), "op": a.name,
                  "value": self.value_display(a.value, kt)}
            st["_orig"] = {"target": (st["target"], a.target), "value": (st["value"], a.value)}

            def apply(**chg):
                st.update(chg)
                self._set_act(key, st)
            self._primary = self._picker(g, 0, "Variable", variables, st["target"], lambda t: apply(target=t),
                                         "The variable this action changes. Type to search.")
            self._combo(g, 1, "Do", [w for w, _n in emtext.ACTION_CHOICES],
                        next((w for w, n in emtext.ACTION_CHOICES if n == a.name), a.name),
                        lambda w: apply(op=dict(emtext.ACTION_CHOICES)[w]), "What to do with the value.")
            vals = self.value_choices(kt) or []
            self._picker(g, 2, "Value", vals + operands, st["value"], lambda t: apply(value=t),
                         "A number, a named value, or a game value / variable to use.")
        self._buttons(b, [
            ("Add an action before", lambda: self.add_action_to(stream, ai),
             "Insert an action above this one (starts as 'run entry #0', which does nothing)."),
            ("Add an action after", lambda: self.add_action_to(stream, ai + 1),
             "Insert an action below this one."),
            ("Remove", self.remove_selected, "Remove this action (Del)."),
        ])

    def _switch_act(self, key, mode):
        if mode == "call":
            act = emscript.Action(0x00, "CALL", entry=0)
        else:
            var = self.names.flags.variables[0]
            act = self.em.parse_action_spec("%s += 0" % var.name)
        self._edit("Change action of em.bin #%d" % self.idx,
                   lambda: self.em.replace_action(self.idx, key[1], key[2], act), select=key)

    def _set_call(self, key, entry):
        if entry is None:
            return
        act = emscript.Action(0x10 if entry > 0xFFFF else 0x00, "CALL", entry=entry)
        self._edit("Change action of em.bin #%d" % self.idx,
                   lambda: self.em.replace_action(self.idx, key[1], key[2], act), select=key)

    def _set_act(self, key, st):
        try:
            t, v = self._keep_or_parse(st, "target"), self._keep_or_parse(st, "value")
        except ValueError as ex:
            messagebox.showerror("Action", str(ex), parent=self.win)
            return self.show_form(key)
        if t.kind != "flag":
            messagebox.showerror("Action", "An action can only change a variable (FLG_ / REG_ …).",
                                 parent=self.win)
            return self.show_form(key)
        act = emscript.Action(self.em._ACT_NIBBLE[st["op"]], st["op"], target=t, value=v)
        return self._edit("Change action of em.bin #%d" % self.idx,
                          lambda: self.em.replace_action(self.idx, key[1], key[2], act), select=key)

    # ---- edits (all through the document: undoable, counted as unsaved) ----------------- #
    def _edit(self, label, fn, select=None, idx=None):
        idx = self.idx if idx is None else idx
        try:
            with self.doc.edit(label):
                out = fn()
        except Exception as ex:  # noqa: BLE001 - report; the document rolled back
            messagebox.showerror("Event Manager", str(ex), parent=self.win)
            self.show_entry(self.idx, keep_sel=True)
            return None
        # the document's change notice already refilled the view; land on the edited line
        if idx is not None and self.entry(idx) is not None:
            self.show_entry(idx, keep_sel=True, select=select)
        self.set_status(label + "  (em.bin unsaved)")
        return out if out is not None else True

    def add_way(self, which):
        e = self.entry()
        if e is None:
            return None
        n = len((e.cond_a if which == "a" else e.cond_b) or ())
        return self._edit("Add a way to em.bin #%d" % e.idx,
                          lambda: self.em.add_condition(e.idx, which, [self.em.make_expr("FALSE")]),
                          select=("expr", which, n, 0))

    def add_requirement(self, which, si, xi, link):
        e = self.entry()
        placeholder = "FALSE" if link == "or" else "TRUE"
        box = {}

        def do():
            box["i"] = self.em.insert_expr(e.idx, which, si, xi, self.em.make_expr(placeholder), link=link)
        if self._edit("Add a requirement to em.bin #%d" % e.idx, do) is None:
            return None
        self.show_entry(self.idx, keep_sel=True, select=("expr", which, si, box["i"]))
        self.set_status("New requirement (%s, so nothing changes yet) — pick what it checks"
                        % ("never true" if link == "or" else "always true"))
        return box["i"]

    def add_action_to(self, stream, index=None):
        e = self.entry()
        if e is None:
            return None
        acts = e.actions if stream == "main" else e.alt_actions
        pos = len(acts) if index is None else index
        act = emscript.Action(0x00, "CALL", entry=0)               # entry #0 is empty: a no-op
        if self._edit("Add an action to em.bin #%d" % e.idx,
                      lambda: self.em.add_action(e.idx, stream, act, index=pos),
                      select=("act", stream, pos)) is None:
            return None
        self.set_status("New action (runs entry #0, which does nothing) — pick what it does")
        return pos

    def remove_way(self, which, si):
        e = self.entry()
        return self._edit("Remove a way from em.bin #%d" % e.idx,
                          lambda: self.em.remove_condition(e.idx, which, si), select=("entry",))

    def remove_selected(self):
        k, e = self.sel, self.entry()
        if e is None or not k:
            return None
        if k[0] == "expr":
            return self._edit("Remove a requirement from em.bin #%d" % e.idx,
                              lambda: self.em.remove_condition(e.idx, k[1], k[2], k[3]),
                              select=("sec", k[1]))
        if k[0] == "act":
            return self._edit("Remove an action from em.bin #%d" % e.idx,
                              lambda: self.em.remove_action(e.idx, k[1], k[2]), select=("entry",))
        if k[0] == "slot":
            return self.remove_way(k[1], k[2])
        return None

    def add_entry(self):
        name = simpledialog.askstring("New entry", "A name for the new entry (only shown in the toolkit: "
                                      "the game refers to entries by number). Blank for none.",
                                      parent=self.win)
        if name is None:
            return None
        box = {}
        if self._edit("Add em.bin entry", lambda: box.update(i=self.em.add_entry(name=name.strip())),
                      idx=-1) is None:
            return None
        self._counts = None
        self.q.set("")
        self.fill_browser()
        self.open_entry(box["i"])
        return box["i"]

    def copy_entry(self):
        e = self.entry()
        if e is None:
            messagebox.showinfo("Copy entry", "Open an entry first.", parent=self.win)
            return None
        box = {}
        if self._edit("Copy em.bin entry %d" % e.idx,
                      lambda: box.update(i=self.em.add_entry(clone=e.idx, name=(e.name or "") + "_COPY")),
                      idx=-1) is None:
            return None
        self._counts = None
        self.q.set("")
        self.fill_browser()
        self.open_entry(box["i"])
        return box["i"]

    def remove_entry(self):
        e = self.entry()
        if e is None:
            messagebox.showinfo("Remove entry", "Open an entry first.", parent=self.win)
            return None
        uses, refs = self.uses(e.idx), self.refs(e.idx)
        later = len(self.em.entries) - e.idx - 1
        msg = "Remove #%d %s?" % (e.idx, self.label(e.idx))
        if uses:
            msg += "\n\n%d scene statement%s use it by number — they are NOT updated." % (
                len(uses), "" if len(uses) == 1 else "s")
        if later:
            msg += ("\n\nThe %d entr%s after it move down one number. References inside em.bin are "
                    "renumbered; scenes (rf3.mc) are not." % (later, "y" if later == 1 else "ies"))
        if refs:
            msg += "\n\nUsed by %d other entr%s, so it will be emptied in place instead (numbers stay)." % (
                len(refs), "y" if len(refs) == 1 else "ies")
        if not messagebox.askyesno("Remove entry", msg, parent=self.win):
            return None
        idx = e.idx
        if refs or uses:
            how = "cleared"
            ok = self._edit("Clear em.bin entry %d" % idx, lambda: self.em.clear_entry(idx))
        else:
            how = "deleted"
            ok = self._edit("Remove em.bin entry %d" % idx, lambda: self.em.delete_entry(idx), idx=-1)
            self.idx = None
        if ok is None:
            return None
        self._counts = None
        self.fill_browser()
        self.show_entry(self.idx)
        self.set_status("em.bin: entry %d %s (unsaved)" % (idx, how))
        return how

    def type_it(self):
        """Add a condition or an action by typing it (the old spec language)."""
        e = self.entry()
        if e is None:
            messagebox.showinfo("Type it", "Open an entry first.", parent=self.win)
            return None
        prompt = ("For #%d %s — type a condition (adds a new way) or an action.\n\n"
                  % (e.idx, self.label(e.idx)) + catalog.EM_CONDITION_SYNTAX_HELP + "\n\n"
                  + catalog.EM_ACTION_SYNTAX_HELP)

        def classify(t):
            try:
                return "act", parse_action(self.em, t)
            except ValueError:
                return "cond", parse_condition(self.em, self.em.entries[e.idx], t)
        spec = self.app.ask_spec("Type it", prompt, classify)
        if not spec:
            return None
        kind, parsed = classify(spec)
        idx = e.idx
        if kind == "act":
            stream, action = parsed
            n = len(self.em.entries[idx].actions if stream == "main" else self.em.entries[idx].alt_actions)
            return self._edit("Add an action to em.bin #%d" % idx,
                              lambda: self.em.add_action(idx, stream, action), select=("act", stream, n))
        which, slot, exprs = parsed
        return self._edit("Add a condition to em.bin #%d" % idx,
                          lambda: self.em.add_condition(idx, which, exprs, slot=slot), select=("sec", which))
