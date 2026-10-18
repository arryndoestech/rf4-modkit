"""The scene browser: every bank grouped (maps, characters, villager behaviour, sub-events,
the opening bank) with readable names, its scenes listed on demand, and search."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from guiutil import Tip, later
from rf4s_modkit import script

from . import catalog
from .render import scene_preview

ALL_TRIGGERS = "all triggers"

SEARCH_MODES = ("dialogue", "speaker", "opcode", "variable", "event manager entry", "bank #")


def scene_rows(bank):
    """Scenes of a bank, one per entry pc: typed (triggered) scenes first, then the
    unreached code (found by the gap-fill scan: nothing in the bank registers or CALLs it),
    each in bytecode order."""
    seen, typed = set(), []
    scenes = script.disassemble_bank(bank)
    for sc in scenes:
        if sc.action_type >= 0 and sc.entry_pc not in seen:
            seen.add(sc.entry_pc)
            typed.append(sc)
    subs = []
    for sc, own in script.unreached(scenes):      # judged by the code only they reach
        if sc.entry_pc not in seen:
            seen.add(sc.entry_pc)
            sc.own_count = len(own)
            subs.append(sc)
    return sorted(typed, key=lambda s: s.entry_pc) + sorted(subs, key=lambda s: s.entry_pc)


def scene_label(doc, sc):
    if sc.action_type >= 0:
        kind = catalog.type_label(sc.action_type).split("  ", 1)[-1]
    else:
        own = getattr(sc, "own_count", None)
        kind = "unreached" + (" (%d statement%s)" % (own, "" if own == 1 else "s") if own else "")
    flag = "" if sc.ok else " ⚠"
    return f"@{sc.entry_pc:04x}  {kind}{flag} · {scene_preview(doc, sc)}"


def called_subroutines(sc):
    """The CALL targets a scene reaches (its own and those of the subroutines it calls), in
    the order the calls appear: [(target pc, number of CALL sites)]."""
    out = {}
    for _pc, st in sc.stmts.items():
        if st.mnem == "CALL" and st.code_targets and st.code_targets[0] in sc.stmts:
            t = st.code_targets[0]
            out[t] = out.get(t, 0) + 1
    return list(out.items())


def subroutine_label(doc, bank, target, n_calls):
    """Row text for a subroutine under its scene: its address and a one-line preview."""
    try:
        sub = script.disassemble_scene(bank, -1, target)
        prev = scene_preview(doc, sub)
    except Exception:  # noqa: BLE001 -- a label only
        prev = ""
    calls = "" if n_calls == 1 else f" ({n_calls} calls)"
    return f"calls sub @{target:04x}{calls} · {prev}"


class Browser(ttk.Frame):
    """The left pane: a Banks tab (every bank, grouped, with its scenes) and a Search tab (the
    search box and its results), so results never push the bank list down."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=2, pady=2)
        # ---- Banks tab ----
        banks = ttk.Frame(self.nb)
        self.nb.add(banks, text="Banks")
        self.banks_tab = banks
        br = ttk.Frame(banks)
        br.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Label(br, text="Trigger type").pack(side="left")
        self.show_empty = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(br, text="empty banks", variable=self.show_empty, command=self.rebuild)
        cb.pack(side="right", padx=(4, 0))          # packed before the dropdown: never squeezed out
        Tip(cb, "Also list banks with no scene yet (most maps).")
        self.type_filter = tk.StringVar(value=ALL_TRIGGERS)
        self._type_ids = {ALL_TRIGGERS: None}       # dropdown text -> trigger type (None = all)
        tc = ttk.Combobox(br, textvariable=self.type_filter, values=[ALL_TRIGGERS], width=12,
                          state="readonly")
        tc.pack(side="left", fill="x", expand=True, padx=(4, 0))   # takes whatever room is left
        tc.bind("<<ComboboxSelected>>", lambda _e: self.rebuild())
        self.type_combo = tc
        Tip(tc, "Show only the scenes of one trigger type (what makes a scene "
                "run: entering a map, a talk line, a warp, a festival...), and only the banks "
                "that have one. The number is how many triggers of that type ship. The Reference "
                "window's Trigger types tab explains each type.")
        self.tree = self._tree(banks)
        self.tree.bind("<<TreeviewOpen>>", self._opened)
        self.tree.bind("<<TreeviewSelect>>", self._picked)
        # ---- Search tab ----
        srch = ttk.Frame(self.nb)
        self.nb.add(srch, text="Search")
        self.search_tab = srch
        top = ttk.Frame(srch)
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
        mr = ttk.Frame(srch)
        mr.pack(fill="x", padx=4)
        ttk.Label(mr, text="in").pack(side="left")
        self.mode = tk.StringVar(value="dialogue")
        mc = ttk.Combobox(mr, textvariable=self.mode, values=SEARCH_MODES, state="readonly", width=20)
        mc.pack(side="left", padx=4)
        Tip(mc, "dialogue: what someone says or a choice-menu option · speaker: who speaks · opcode: an action by name or "
                "number · variable: a FLG_ / REG_ / EV_ name (reads and writes) · event manager entry: an "
                "em.bin entry name · bank #: open a bank (in the Banks tab).")
        self.summary = ttk.Label(srch, text="No search yet.", foreground="#0d5f8f", anchor="w")
        self.summary.pack(fill="x", padx=6, pady=(4, 0))
        self.results = self._tree(srch)
        self.results.bind("<<TreeviewSelect>>", self._picked_result)
        self._rows = {}                     # Banks tab: iid -> ("bank", pos) | ("scene", pos, entry)
        #                                          | ("sub", pos, entry, target)
        self._results = {}                  # Search tab: iid -> ("result", pos, entry, pc of the first match)
        self._syncing = False

    def _tree(self, parent):
        f = ttk.Frame(parent)
        f.pack(fill="both", expand=True, padx=4, pady=4)
        t = ttk.Treeview(f, show="tree", selectmode="browse")
        sb = ttk.Scrollbar(f, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        t.column("#0", width=300)
        t.tag_configure("result", foreground="#0d5f8f")
        t.tag_configure("dim", foreground="#888")
        return t

    def show_search(self):
        """The Search tab with the cursor in the search box (Ctrl+F)."""
        self.nb.select(self.search_tab)
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    # ---- building ----------------------------------------------------------- #
    def rebuild(self):
        t = self.tree
        t.delete(*t.get_children())
        self._rows.clear()
        doc = self.app.doc
        if doc.container is None:
            return
        if self._names_ready:
            catalog.refresh_subevent_names(doc)   # town-event bank titles follow the language
        elif self._names_job is None:
            # the first time naming them parses the dialogue file and the global bank (a third
            # of a second): the list shows first, the town-event titles follow
            self._names_job = later(self, self._late_names, self.LATE_NAMES_MS)
        want = self._refresh_type_filter(doc)
        groups = {g: [] for g, _t in catalog.GROUP_TITLES}
        empty = self.show_empty.get()
        for pos, bank in enumerate(doc.container.banks):
            if want is not None:
                if want in bank.type_table_full():
                    groups[catalog.bank_group(bank)].append(pos)
            elif empty or not catalog.bank_is_empty(bank):
                groups[catalog.bank_group(bank)].append(pos)
        for g, title in catalog.GROUP_TITLES:
            if not groups[g]:
                continue
            gid = t.insert("", "end", iid=f"g:{g}", text=f"{title}  ({len(groups[g])})", open=(g == "global"))
            for pos in groups[g]:
                self._add_bank(gid, pos)

    LATE_NAMES_MS = 250
    _names_ready = False
    _names_job = None

    def _late_names(self):
        """The town-event banks' titles, once the editor shows: named, then relabelled."""
        self._names_job = None
        try:
            if not self.tree.winfo_exists():
                return
        except tk.TclError:
            return
        doc = self.app.doc
        self._names_ready = True
        if doc.container is None:
            return
        catalog.refresh_subevent_names(doc)
        for pos, bank in enumerate(doc.container.banks):
            iid = "b:%d" % pos
            if self.tree.exists(iid):
                title = catalog.bank_title(bank)
                if self.tree.item(iid, "text") != title:
                    self.tree.item(iid, text=title)

    def _refresh_type_filter(self, doc):
        """Fill the Trigger type dropdown with the trigger types the open file uses (trigger counts
        across every bank) and return the chosen type, or None for all."""
        counts = {}
        for bank in doc.container.banks:
            for t, (n, _off) in bank.type_table_full().items():
                counts[t] = counts.get(t, 0) + n
        self._type_ids = {ALL_TRIGGERS: None}
        for t in sorted(counts):
            self._type_ids["%s  (%d)" % (catalog.type_label(t)[5:], counts[t])] = t
        self.type_combo.config(values=list(self._type_ids))
        cur = self._type_ids.get(self.type_filter.get(), "gone")
        if cur == "gone":                       # its count changed (an edit) or it is gone
            old = getattr(self, "_type_want", None)
            hit = next((k for k, v in self._type_ids.items() if v == old and old is not None), None)
            self.type_filter.set(hit or ALL_TRIGGERS)
            cur = self._type_ids[self.type_filter.get()]
        self._type_want = cur
        return cur

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
        want = getattr(self, "_type_want", None)
        if want is not None:                    # the Trigger type filter: scenes of that type only
            pcs = {r.event_id for r in bank.entry_records(want)}
            scenes = [sc for sc in scenes if sc.entry_pc in pcs]
        previews = {}                       # subroutine pc -> its label (shared by many scenes)
        for sc in scenes:
            sid = f"s:{pos}:{sc.entry_pc}"
            t.insert(iid, "end", iid=sid, text=scene_label(doc, sc))
            self._rows[sid] = ("scene", pos, sc.entry_pc)
            # the subroutines it CALLs (the Graph tab draws each as its own group)
            for target, n in called_subroutines(sc):
                cid = f"c:{pos}:{sc.entry_pc}:{target}"
                if (target, n) not in previews:
                    previews[(target, n)] = subroutine_label(doc, bank, target, n)
                t.insert(sid, "end", iid=cid, text=previews[(target, n)], tags=("dim",))
                self._rows[cid] = ("sub", pos, sc.entry_pc, target)
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
        elif row[0] == "sub":                   # the calling scene, at the subroutine's start
            self.app.open_scene(row[1], row[2], focus_pc=row[3], reveal=False)
        else:
            self.app.open_scene(row[1], row[2])

    def _picked_result(self, _e=None):
        if self._syncing:
            return
        s = self.results.selection()
        row = self._results.get(s[0]) if s else None
        if row is not None:                     # open at the match, leave the Banks tab alone
            self.app.open_scene(row[1], row[2], focus_pc=row[3], reveal=False)

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
            self.nb.select(self.banks_tab)
            self.app.open_bank(pos)
            return
        if mode == "dialogue" and doc.textarc is None:
            self.app.status(f"rf3mc.{doc.locale} is not loaded — cannot search dialogue")
            return
        if mode == "variable" and getattr(doc, "emf_vars", None) is None:
            self.app.status("emdeb.bin is not loaded — cannot search variables by name")
            return
        self.app.busy(True)
        try:
            hits = self._find(mode, q)
        finally:
            self.app.busy(False)
        t = self.results
        t.delete(*t.get_children())
        self._results.clear()
        self.summary.config(text=f"“{q}” in {mode}: {len(hits)} scene(s)")
        match = statement_matcher(doc, mode, q)
        for n, (pos, sc) in enumerate(hits):
            iid = f"r:{n}"
            bank = doc.container.banks[pos]
            t.insert("", "end", iid=iid, text=f"{catalog.bank_title(bank)} · {scene_label(doc, sc)}",
                     tags=("result",))
            self._results[iid] = ("result", pos, sc.entry_pc, first_match_pc(bank, sc, match))
        t.yview_moveto(0)
        self.nb.select(self.search_tab)
        if hits:
            # highlight the first hit and open it at the matching line
            self._syncing = True
            try:
                t.selection_set("r:0")
                t.focus("r:0")
            finally:
                later(self, lambda: setattr(self, "_syncing", False))
            _k, pos, entry, pc = self._results["r:0"]
            self.app.open_scene(pos, entry, focus_pc=pc, reveal=False)
        self.app.status(f"{len(hits)} scene(s) match {mode} “{q}”")

    def _find(self, mode, q):
        return find_scenes(self.app.doc, mode, q)


def statement_matcher(doc, mode, q):
    """fn(bank, statement) -> bool for one search mode ("dialogue", "speaker", "opcode" by
    mnemonic, name or number, "variable" by FLG_ / REG_ / EV_ name, "event manager entry"),
    or None when the mode can't match (dialogue with the locale not loaded, variable without
    emdeb.bin, event manager entry without em.bin)."""
    ql = q.lower()
    if mode == "dialogue":
        if doc.textarc is None:
            return None

        def dialogue(_bk, st):
            for i in script.statement_text_ids(st):   # DIALOG lines and choice-menu options
                try:
                    s = doc.text(i)
                except Exception:  # noqa: BLE001 - a line outside the archive
                    s = None
                if s and ql in s.lower():
                    return True
            return False
        return dialogue
    if mode == "speaker":
        return lambda _bk, st: (script.is_portrait_op(st.op)
                                and ql in (script.portrait_speaker_name(st.op) or "").lower())
    if mode == "opcode":
        try:
            qnum = int(q, 0)
        except ValueError:
            qnum = None
        def opcode(_bk, st):
            if qnum is not None and st.op == qnum:
                return True
            if st.op >= 0xFFF0:                     # control: SWITCH, JMP, CALL, BR_Z, menus, ...
                return ql in (st.mnem or "").lower()
            return ql in script.opcode_mnemonic(st.op).lower() or ql in script.opcode_name(st.op).lower()
        return opcode
    if mode == "variable":
        tbl = getattr(doc, "emf_vars", None)
        if tbl is None:
            return None
        # every emdeb variable whose name contains the query, keyed as the scripts store it
        keys = {(v.bit_offset, v.bit_width) for v in tbl.variables if ql in v.name.lower()}
        if not keys:
            return lambda _bk, _st: False
        from rf4s_modkit import varuses
        unpack = doc.container.unpack_var

        def variable(bk, st):
            return any(unpack(enc)[:2] in keys for enc, _acc in varuses.statement_var_access(bk.data, st))
        return variable
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
