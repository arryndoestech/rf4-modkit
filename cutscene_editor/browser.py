"""The scene browser: every bank grouped (maps, characters, villager behaviour, sub-events,
the opening bank) with readable names, its scenes listed on demand, and search."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from guiutil import Tip, later
from rf4s_modkit import script

from . import catalog
from .render import scene_preview

SEARCH_MODES = ("dialogue", "speaker", "opcode", "event manager entry", "bank #")


def scene_rows(bank):
    """Scenes of a bank, one per entry pc: typed (triggered) scenes first, then the
    discovered subroutines, each in bytecode order."""
    seen, typed, subs = set(), [], []
    for sc in script.disassemble_bank(bank):
        if sc.entry_pc in seen:
            continue
        seen.add(sc.entry_pc)
        (typed if sc.action_type >= 0 else subs).append(sc)
    return sorted(typed, key=lambda s: s.entry_pc) + sorted(subs, key=lambda s: s.entry_pc)


def scene_label(doc, sc):
    kind = catalog.type_label(sc.action_type).split("  ", 1)[-1] if sc.action_type >= 0 else "subroutine"
    flag = "" if sc.ok else " ⚠"
    return f"@{sc.entry_pc:04x}  {kind}{flag} · {scene_preview(doc, sc)}"


class Browser(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        top = ttk.Frame(self)
        top.pack(fill="x", padx=4, pady=(4, 2))
        self.q = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.q)
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda _e: self.search())
        self.search_entry = e
        Tip(e, "Search every scene (Enter). Pick what to search in the box below. Ctrl+F "
               "jumps here.")
        fb = ttk.Button(top, text="Find", width=5, command=self.search)
        fb.pack(side="left", padx=(2, 0))
        Tip(fb, "Search every scene for the text above.")
        mr = ttk.Frame(self)
        mr.pack(fill="x", padx=4)
        ttk.Label(mr, text="in").pack(side="left")
        self.mode = tk.StringVar(value="dialogue")
        mc = ttk.Combobox(mr, textvariable=self.mode, values=SEARCH_MODES, state="readonly", width=20)
        mc.pack(side="left", padx=4)
        Tip(mc, "dialogue: what someone says · speaker: who speaks · opcode: an action by name or "
                "number · event manager entry: an em.bin entry name · bank #: open a bank.")
        self.show_empty = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(mr, text="empty banks", variable=self.show_empty, command=self.rebuild)
        cb.pack(side="right")
        Tip(cb, "Also list banks with no scene yet (most maps): the Triggers tab mints a first one.")
        f = ttk.Frame(self)
        f.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree = ttk.Treeview(f, show="tree", selectmode="browse")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.column("#0", width=300)
        self.tree.tag_configure("result", foreground="#0d5f8f")
        self.tree.tag_configure("dim", foreground="#888")
        self.tree.bind("<<TreeviewOpen>>", self._opened)
        self.tree.bind("<<TreeviewSelect>>", self._picked)
        self._rows = {}                     # iid -> ("bank", pos) | ("scene", pos, entry)
        #                                          | ("result", pos, entry, pc of the first match)
        self._syncing = False

    # ---- building ----------------------------------------------------------- #
    def rebuild(self):
        t = self.tree
        t.delete(*t.get_children())
        self._rows.clear()
        doc = self.app.doc
        if doc.container is None:
            return
        groups = {g: [] for g, _t in catalog.GROUP_TITLES}
        empty = self.show_empty.get()
        for pos, bank in enumerate(doc.container.banks):
            if empty or not catalog.bank_is_empty(bank):
                groups[catalog.bank_group(bank)].append(pos)
        for g, title in catalog.GROUP_TITLES:
            if not groups[g]:
                continue
            gid = t.insert("", "end", iid=f"g:{g}", text=f"{title}  ({len(groups[g])})", open=(g == "global"))
            for pos in groups[g]:
                self._add_bank(gid, pos)

    def _add_bank(self, parent, pos):
        bank = self.app.doc.container.banks[pos]
        iid = self.tree.insert(parent, "end", iid=f"b:{pos}", text=catalog.bank_title(bank),
                               tags=("dim",) if catalog.bank_is_empty(bank) else ())
        self._rows[iid] = ("bank", pos)
        self.tree.insert(iid, "end", iid=f"b:{pos}:…", text="…")     # filled when opened

    def _fill_bank(self, pos):
        t = self.tree
        iid = f"b:{pos}"
        if not t.exists(iid):
            return
        t.delete(*t.get_children(iid))
        doc = self.app.doc
        bank = doc.container.banks[pos]
        scenes = scene_rows(bank)
        for sc in scenes:
            sid = f"s:{pos}:{sc.entry_pc}"
            t.insert(iid, "end", iid=sid, text=scene_label(doc, sc))
            self._rows[sid] = ("scene", pos, sc.entry_pc)
        if not scenes:
            t.insert(iid, "end", text="(no scenes — Triggers tab: New scene…)", tags=("dim",))

    def _opened(self, _e=None):
        iid = self.tree.focus()
        if iid.startswith("b:") and self.tree.exists(f"{iid}:…"):
            self._fill_bank(int(iid[2:]))

    def relabel(self):
        """Re-title the bank rows (their names come from the game's name files)."""
        banks = self.app.doc.container.banks if self.app.doc.container is not None else []
        for iid, row in self._rows.items():
            if row[0] == "bank" and self.tree.exists(iid) and row[1] < len(banks):
                self.tree.item(iid, text=catalog.bank_title(banks[row[1]]))

    def refresh_bank(self, pos):
        """Re-list a bank's scenes after an edit (only when it is already expanded)."""
        iid = f"b:{pos}"
        if self.tree.exists(iid) and not self.tree.exists(f"{iid}:…"):
            self._fill_bank(pos)

    # ---- selection ------------------------------------------------------------- #
    def _picked(self, _e=None):
        if self._syncing:
            return
        s = self.tree.selection()
        row = self._rows.get(s[0]) if s else None
        if row is None:
            return
        if row[0] == "bank":
            self.app.open_bank(row[1])
        elif row[0] == "result":
            self.app.open_scene(row[1], row[2], focus_pc=row[3], reveal=False)
        else:
            self.app.open_scene(row[1], row[2])

    def reveal(self, pos, entry=None):
        """Expand to and select a bank (and scene) without re-triggering the open."""
        t = self.tree
        bid = f"b:{pos}"
        if not t.exists(bid):
            bank = self.app.doc.container.banks[pos]
            gid = f"g:{catalog.bank_group(bank)}"
            if not t.exists(gid):
                return
            self._add_bank(gid, pos)
        t.item(t.parent(bid), open=True)
        if t.exists(f"{bid}:…"):
            self._fill_bank(pos)
        target = bid
        if entry is not None and t.exists(f"s:{pos}:{entry}"):
            t.item(bid, open=True)
            target = f"s:{pos}:{entry}"
        self._syncing = True
        try:
            t.selection_set(target)
            t.see(target)
        finally:
            later(self, lambda: setattr(self, "_syncing", False))

    # ---- search -------------------------------------------------------------------- #
    def search(self):
        doc = self.app.doc
        q = self.q.get().strip()
        if doc.container is None or not q:
            return
        mode = self.mode.get()
        if mode == "bank #":
            try:
                pos = int(q.lstrip("b"), 0)
                doc.container.banks[pos]
            except (ValueError, IndexError):
                self.app.status(f"no bank {q} (0..{len(doc.container.banks) - 1})")
                return
            self.app.open_bank(pos)
            return
        if mode == "dialogue" and doc.textarc is None:
            self.app.status(f"rf3mc.{doc.locale} is not loaded — cannot search dialogue")
            return
        self.app.busy(True)
        try:
            hits = self._find(mode, q)
        finally:
            self.app.busy(False)
        t = self.tree
        if t.exists("results"):
            for c in t.get_children("results"):
                self._rows.pop(c, None)
            t.delete("results")
        rid = t.insert("", 0, iid="results", text=f"Results for “{q}” in {mode}: {len(hits)} scene(s)",
                       open=True, tags=("result",))
        match = statement_matcher(doc, mode, q)
        for n, (pos, sc) in enumerate(hits):
            iid = f"r:{n}"
            bank = doc.container.banks[pos]
            t.insert(rid, "end", iid=iid, text=f"{catalog.bank_title(bank)} · {scene_label(doc, sc)}",
                     tags=("result",))
            self._rows[iid] = ("result", pos, sc.entry_pc, first_match_pc(bank, sc, match))
        t.yview_moveto(0)
        if hits:
            # highlight the first hit and open it at the matching line
            self._syncing = True
            try:
                t.selection_set("r:0")
                t.focus("r:0")
            finally:
                later(self, lambda: setattr(self, "_syncing", False))
            _k, pos, entry, pc = self._rows["r:0"]
            self.app.open_scene(pos, entry, focus_pc=pc, reveal=False)
        self.app.status(f"{len(hits)} scene(s) match {mode} “{q}”")

    def _find(self, mode, q):
        return find_scenes(self.app.doc, mode, q)


def statement_matcher(doc, mode, q):
    """fn(bank, statement) -> bool for one search mode ("dialogue", "speaker", "opcode" by
    mnemonic, name or number, "event manager entry"), or None when the mode can't match
    (dialogue with the locale not loaded, event manager entry without em.bin)."""
    ql = q.lower()
    if mode == "dialogue":
        if doc.textarc is None:
            return None

        def dialogue(_bk, st):
            if st.mnem != "DIALOG":
                return False
            try:
                s = doc.text(st.dialog_id)
            except Exception:  # noqa: BLE001 - a line outside the archive
                s = None
            return bool(s) and ql in s.lower()
        return dialogue
    if mode == "speaker":
        return lambda _bk, st: (script.is_portrait_op(st.op)
                                and ql in (script.portrait_speaker_name(st.op) or "").lower())
    if mode == "opcode":
        try:
            qnum = int(q, 0)
        except ValueError:
            qnum = None
        return lambda _bk, st: st.op < 0xFFF0 and (
            (qnum is not None and st.op == qnum) or ql in script.opcode_mnemonic(st.op).lower()
            or ql in script.opcode_name(st.op).lower())
    if mode == "event manager entry":
        em = doc.em
        if em is None:
            return None

        def entry(bk, st):
            ai = script.EMF_ENTRY_OPS.get(st.op)
            if ai is None or ai >= len(st.args):
                return False
            try:
                nm = em.names.entry_name(int(script.arg_repr(bk.data, st.args[ai])))
            except (ValueError, TypeError):
                nm = None
            return bool(nm) and ql in nm.lower()
        return entry
    return None


def first_match_pc(bank, sc, match):
    """The first matching statement of a scene in play order (then the other branches)."""
    if match is None:
        return None
    lin = script.linearize(sc)
    shown = {pc for pc, _ in lin}
    for pc, st in lin + [(pc, st) for pc, st in sc.stmts.items() if pc not in shown]:
        if match(bank, st):
            return pc
    return None


def find_scenes(doc, mode, q):
    """Scenes matching `q` in one search mode (statement_matcher), as [(bank_pos, scene)] in
    bank order. Dialogue search returns [] when the current locale is not loaded."""
    c = doc.container
    match = statement_matcher(doc, mode, q)
    if match is None:
        return []
    pos_of = {id(b): i for i, b in enumerate(c.banks)}
    out, seen = [], set()
    for bk, sc in script.iter_scenes(c):
        key = (id(bk), sc.entry_pc)
        if key not in seen and any(match(bk, st) for st in sc.stmts.values()):
            seen.add(key)
            out.append((pos_of[id(bk)], sc))
    return sorted(out, key=lambda r: (r[0], r[1].entry_pc))
