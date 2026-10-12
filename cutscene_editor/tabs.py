"""The Source, Triggers and Overview tabs."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from guiutil import FilterCombo, Paned, ScrollFrame, Tip
from guiutil import err_text
from rf4s_modkit import script, scriptasm, subevents

from . import catalog
from .render import SceneText

DARK = dict(bg="#15151b", fg="#dcdce4", insertbackground="#dcdce4")


def count_statements(text):
    """Statements in a listing (labels, comments and blank lines excluded)."""
    n = 0
    for raw in (text or "").splitlines():
        s = raw.split(";", 1)[0].strip()
        for _ in range(4):
            s2 = re.sub(r"^(?:[A-Za-z_]\w*|[0-9A-Fa-f]{4})\s*:(?!:)\s*", "", s)
            if s2 == s:
                break
            s = s2
        if s:
            n += 1
    return n


# --------------------------------------------------------------------------- #
_ADDR = re.compile(r"^(\s*)([0-9a-fA-F]{4}): ")      # a listing line's "0123: " prefix


def strip_addresses(lines):
    """(lines without their "0123: " address prefix, [pc | None per line])."""
    out, pcs = [], []
    for ln in lines:
        m = _ADDR.match(ln)
        if m:
            out.append(m.group(1) + ln[m.end():])
            pcs.append(int(m.group(2), 16))
        else:
            out.append(ln)
            pcs.append(None)
    return out, pcs


class AddressColumn:
    """The statements' addresses (toolbar: "addresses") in a read-only column to the left of
    a listing Text, scrolling with it -- so the text itself never carries them. Installs
    itself as the Text's y-scroll handler (feeding `scrollbar` too)."""

    def __init__(self, box, text, scrollbar):
        self.text, self.sb = text, scrollbar
        self.col = tk.Text(box, width=5, wrap="none", font=text.cget("font"), bg="#101015",
                           fg="#6a6a7a", borderwidth=0, highlightthickness=0, state="disabled",
                           takefocus=0, cursor="arrow", padx=4)
        text.config(yscrollcommand=self._yscroll)
        scrollbar.config(command=self._yview)
        self.col.bind("<MouseWheel>", lambda e: (text.yview_scroll(-1 if e.delta > 0 else 1,
                                                                   "units"), "break")[1])

    def _yscroll(self, first, last):
        self.sb.set(first, last)
        self.col.yview_moveto(first)

    def _yview(self, *a):
        self.text.yview(*a)
        self.col.yview_moveto(self.text.yview()[0])

    def show(self, on):
        if not on:
            self.col.pack_forget()
        elif not self.col.winfo_manager():
            self.col.pack(side="left", fill="y", before=self.text)

    def set_rows(self, rows):
        """One entry per text line: an address (int) or None for a blank."""
        c = self.col
        c.config(state="normal")
        c.delete("1.0", "end")
        c.insert("1.0", "\n".join("%04x" % r if r is not None else "" for r in rows))
        c.config(state="disabled")
        c.yview_moveto(self.text.yview()[0])


class BankListingTab(ttk.Frame):
    """The whole open bank as one read-only listing (Options -> Advanced): every scene, the
    ones no trigger registers included, one after another in the `rf4mod script listing
    --bank N` format with dialogue comments. Find jumps between matches; a double click opens
    that scene at that statement; Save as... writes the text out."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=2, pady=2)
        ttk.Label(bar, text="Find").pack(side="left", padx=(2, 2))
        self.find_var = tk.StringVar()
        fe = ttk.Entry(bar, textvariable=self.find_var, width=28)
        fe.pack(side="left")
        fe.bind("<Return>", lambda _e: self.find_next())
        fe.bind("<Shift-Return>", lambda _e: self.find_next(back=True))
        Tip(fe, "Enter: next match, Shift+Enter: previous (not case-sensitive).")
        self.find_var.trace_add("write", lambda *_: self._mark_all())
        b = ttk.Button(bar, text="Save as…", command=self.save_as)
        b.pack(side="right", padx=2)
        Tip(b, "Write the listing to a text file.")
        self.info = ttk.Label(bar, text="", font=("Segoe UI", 8), foreground="#666")
        self.info.pack(side="left", padx=8)
        box = ttk.Frame(self)
        box.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(box)
        sb.pack(side="right", fill="y")
        xs = ttk.Scrollbar(box, orient="horizontal")
        xs.pack(side="bottom", fill="x")
        self.text = tk.Text(box, wrap="none", font=("Consolas", 10), yscrollcommand=sb.set,
                            xscrollcommand=xs.set, **DARK)
        self.text.pack(side="left", fill="both", expand=True)
        sb.config(command=self.text.yview)
        xs.config(command=self.text.xview)
        self.addrcol = AddressColumn(box, self.text, sb)
        self.text.tag_configure("cmt", foreground="#7c8c7c")
        self.text.tag_configure("head", foreground="#e0b060")
        self.text.tag_configure("hit", background="#4a4a10")
        self.text.tag_configure("cur", background="#8a6a10")
        self.text.bind("<Double-Button-1>", self._open_line)
        self.text.bind("<Key>", lambda e: None if (e.state & 0x4 or e.keysym in (
            "Up", "Down", "Left", "Right", "Prior", "Next", "Home", "End")) else "break")
        Tip(self.text, "Double-click a statement to open its scene there.")
        self._key = None
        self.line_at = []                   # line number (1-based) - 1 -> (entry_pc, pc | None)

    def render(self, force=False):
        """(Re)build the listing when the bank or its bytes changed since the last time."""
        app = self.app
        bank = getattr(app, "bank", None)
        key = (app.bank_pos, bytes(bank.data) if bank is not None else None, app.doc.locale)
        if not force and key == self._key:
            self.show_addresses()
            return
        self._key = key
        t = self.text
        t.delete("1.0", "end")
        self.line_at = []
        if bank is None:
            self.info.config(text="open a bank on the left")
            return
        parts, n = [], 0
        scenes = script.disassemble_bank(bank)
        keep = {id(sc_) for sc_, _own in script.unreached(scenes)}
        for sc in scenes:
            if sc.action_type < 0 and id(sc) not in keep:
                continue                          # a stub into code a registered scene runs
            try:
                txt = scriptasm.scene_listing(sc, bank, dialog=app.doc.text, bank_no=app.bank_pos)
            except Exception as e:  # noqa: BLE001 -- one broken scene must not hide the rest
                txt = "; scene @0x%04x: %s" % (sc.entry_pc, err_text(e))
            n += 1
            shown, pcs = strip_addresses(txt.split("\n") + [""])
            for ln, lnpc in zip(shown, pcs):
                self.line_at.append((sc.entry_pc, lnpc))
                parts.append(ln)
        t.insert("1.0", "\n".join(parts))
        for i, ln in enumerate(parts, 1):
            if ln.startswith(";"):
                t.tag_add("head", "%d.0" % i, "%d.end" % i)
            else:
                c = ln.find(";")
                if c >= 0:
                    t.tag_add("cmt", "%d.%d" % (i, c), "%d.end" % i)
        self.info.config(text="%s · %d scenes · %d lines" % (catalog.bank_title(bank), n, len(parts)))
        self.addrcol.set_rows([pc for _e, pc in self.line_at])
        self.show_addresses()
        self._mark_all()

    def show_addresses(self):
        """The address column, while the toolbar's "addresses" is ticked."""
        self.addrcol.show(bool(self.app.addr.get()) if hasattr(self.app, "addr") else False)

    def _mark_all(self):
        t = self.text
        t.tag_remove("hit", "1.0", "end")
        t.tag_remove("cur", "1.0", "end")
        q = self.find_var.get()
        if not q:
            return
        pos, n = "1.0", 0
        while True:
            pos = t.search(q, pos, "end", nocase=True)
            if not pos:
                break
            end = "%s+%dc" % (pos, len(q))
            t.tag_add("hit", pos, end)
            pos, n = end, n + 1
        self.info.config(text=self.info.cget("text").split("  ·  ")[0] + "  ·  %d matches" % n)

    def find_next(self, back=False):
        q = self.find_var.get()
        if not q:
            return
        t = self.text
        start = t.index("insert" if back else "insert+1c")
        pos = t.search(q, start, backwards=back, nocase=True) or t.search(
            q, "end" if back else "1.0", backwards=back, nocase=True)
        if not pos:
            return
        t.tag_remove("cur", "1.0", "end")
        t.tag_add("cur", pos, "%s+%dc" % (pos, len(q)))
        t.mark_set("insert", pos)
        t.xview_moveto(0)                   # keep the addresses / labels in view when the match fits
        t.see(pos)

    def _open_line(self, e):
        line = int(self.text.index("@%d,%d" % (e.x, e.y)).split(".")[0])
        if not 0 < line <= len(self.line_at):
            return "break"
        entry_pc, pc = self.line_at[line - 1]
        self.app.open_scene(self.app.bank_pos, entry_pc, focus_pc=pc, tab="Script")
        return "break"

    def save_as(self):
        from tkinter import filedialog
        app = self.app
        f = filedialog.asksaveasfilename(parent=self, defaultextension=".txt",
                                         initialfile="bank_%s.txt" % app.bank_pos,
                                         filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if f:
            import pathlib
            pathlib.Path(f).write_text(self.text.get("1.0", "end-1c"), encoding="utf-8")
            app.status("bank listing saved to %s" % f)


# --------------------------------------------------------------------------- #
class SourceTab(ttk.Frame):
    """The scene as an editable listing: Check assembles it without applying, Apply makes
    the scene play the new body (appended; the scene's entry jumps to it; nothing moves)."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=2, pady=2)
        for text, cmd, tip in (
                ("Check", self.check, "Assemble without applying: reports the size, or the first "
                                      "error with its line (highlighted)."),
                ("Apply to scene", self.apply, "Assemble this listing and replace the scene with it "
                                               "(Ctrl+Z undoes it)."),
                ("Reload", lambda: self.load(force=True), "Discard hand edits and regenerate the "
                                                         "listing from the scene."),
                ("Syntax help", self.toggle_help, "Show / hide the listing grammar.")):
            b = ttk.Button(bar, text=text, command=cmd)
            b.pack(side="left", padx=2)
            Tip(b, tip)
        self.msg = ttk.Label(self, text="", anchor="w", justify="left", font=("Segoe UI", 8),
                             foreground="#0d5f8f", wraplength=760)
        self.msg.pack(fill="x", padx=4)
        self.help = tk.Label(self, text=catalog.SOURCE_SYNTAX_HELP, justify="left", anchor="w",
                             font=("Consolas", 8), bg="#1b1b22", fg="#e6e6ee", padx=6, pady=4)
        self._help = False
        self.box = ttk.Frame(self)
        self.box.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(self.box)
        sb.pack(side="right", fill="y")
        self.text = tk.Text(self.box, wrap="none", font=("Consolas", 10), undo=True, **DARK)
        self.text.pack(side="left", fill="both", expand=True)
        # the statements' addresses sit in their own column, never in the text you edit;
        # each follows its line through edits (a Text mark)
        self.addrcol = AddressColumn(self.box, self.text, sb)
        self.gutter = self.addrcol.col
        for ev in ("<KeyRelease>", "<<Paste>>", "<<Cut>>", "<<Undo>>", "<<Redo>>"):
            self.text.bind(ev, lambda _e: self._gutter_soon(), add="+")
        self.text.tag_configure("err", background="#5a1a1a")
        self.text.tag_configure("cmt", foreground="#7c8c7c")
        self._key = None
        self._mark_pc = {}               # Text mark name -> statement pc
        self._gutter_after = None

    def set_msg(self, s, kind="info"):
        self.msg.config(text=s, foreground={"ok": "#1d7a3a", "err": "#b02020"}.get(kind, "#0d5f8f"))

    def listing(self):
        """The scene as a re-assemblable listing, without addresses; a leading JMP to the very
        next label (a file an older toolkit trampolined) is dropped, it is plumbing, not content."""
        return "\n".join(self._listing_lines()[0])

    def _listing_lines(self):
        """([line], [pc | None]) of the listing (the pcs feed the address column)."""
        app = self.app
        txt = scriptasm.scene_listing(app.scene, app.bank, dialog=app.doc.text, bank_no=app.bank_pos,
                                      own=script.scene_own_pcs(app.bank, app.scene))
        lines, pcs = strip_addresses(txt.split("\n"))
        for i, ln in enumerate(lines):
            s = ln.strip()
            if not s or s.startswith(";"):
                continue
            m = re.match(r"^(?:[0-9a-fA-F]{4}:\s*)?JMP\s+([A-Za-z_]\w*)\s*(?:;.*)?$", s)
            if m:
                nxt = next((l2.strip() for l2 in lines[i + 1:] if l2.strip()), "")
                if nxt == m.group(1) + ":":
                    del lines[i]
                    del pcs[i]
            break
        return lines, pcs

    def _gutter_soon(self):
        if self._gutter_after is not None:
            try:
                self.after_cancel(self._gutter_after)
            except tk.TclError:
                pass
        self._gutter_after = self.after(120, self.refresh_gutter)

    def refresh_gutter(self):
        """Show / hide the address column (toolbar: "addresses") and fill it from the marks:
        a line keeps its statement's address while you edit around it; a new line has none."""
        self._gutter_after = None
        on = bool(self.app.addr.get())
        self.addrcol.show(on)
        if not on:
            return
        n = int(self.text.index("end-1c").split(".")[0])
        at = {}
        for name, (order, pc) in self._mark_pc.items():
            try:
                ln = int(self.text.index(name).split(".")[0])
            except tk.TclError:
                continue
            # a deleted line's mark lands on the next line: the later statement is that line's
            if ln not in at or order > at[ln][0]:
                at[ln] = (order, pc)
        self.addrcol.set_rows([at[i][1] if i in at else None for i in range(1, n + 1)])

    def load(self, force=False):
        app = self.app
        if app.scene is None:
            self.text.delete("1.0", "end")
            self._key = None
            self.set_msg("(open a scene to see its listing)")
            return
        key = (app.bank_pos, app.scene.entry_pc)
        edited = bool(self.text.edit_modified())
        if not force and key == self._key and edited:
            self.set_msg("listing edited by hand — Check / Apply to scene applies it; Reload discards it")
            return
        self.text.delete("1.0", "end")
        for name in list(self._mark_pc):
            try:
                self.text.mark_unset(name)
            except tk.TclError:
                pass
        self._mark_pc = {}
        lines, pcs = self._listing_lines()
        body = "\n".join(lines)
        self.text.insert("1.0", body)
        for i, pc in enumerate(pcs):
            if pc is not None:
                name = "stmt%d" % i
                self.text.mark_set(name, "%d.0" % (i + 1))
                self.text.mark_gravity(name, "right")    # text typed before it pushes it along
                self._mark_pc[name] = (i, pc)
        for n, ln in enumerate(body.split("\n"), 1):
            c = ln.find(";")
            if c >= 0:
                self.text.tag_add("cmt", "%d.%d" % (n, c), "%d.end" % n)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self._key = key
        self.refresh_gutter()
        n = len(app.scene.stmts)
        self.set_msg("%d statement%s — edit freely, Check, then Apply to scene" % (n, "" if n == 1 else "s"))

    def mark_error(self, msg):
        self.text.tag_remove("err", "1.0", "end")
        m = re.search(r"line (\d+)", msg or "")
        if m:
            ln = int(m.group(1))
            self.text.tag_add("err", "%d.0" % ln, "%d.end" % ln)
            self.text.see("%d.0" % ln)

    def check(self):
        app = self.app
        if app.scene is None:
            return None
        text = self.text.get("1.0", "end-1c")
        if not text.strip():
            self.set_msg("nothing to check (empty listing)", "err")
            return None
        region, labels, err = app.assemble_check(text, strict=False)   # the Source tab allows anything
        if err:
            self.mark_error(err)
            self.set_msg("error: " + err, "err")
            return None
        self.text.tag_remove("err", "1.0", "end")
        n = count_statements(text)
        self.set_msg("OK — %d statement%s assemble to %d bytes; Apply to scene applies it"
                     % (n, "" if n == 1 else "s", len(region)), "ok")
        return region

    def pending(self):
        """True when the listing was edited by hand and differs from the scene (not applied)."""
        if self.app.scene is None or not self.text.edit_modified():
            return False
        return self.text.get("1.0", "end-1c").strip() != self.listing().strip()

    def apply(self):
        app = self.app
        if app.scene is None:
            return False
        text = self.text.get("1.0", "end-1c")
        if not text.strip():
            self.set_msg("nothing to assemble (empty listing)", "err")
            return False
        if text.strip() == self.listing().strip():
            self.set_msg("listing unchanged — nothing to apply")
            return False
        region, _l, err = app.assemble_check(text, strict=False)
        if err:
            self.mark_error(err)
            self.set_msg("error: " + err, "err")
            return False
        same, _l2, _e2 = app.assemble_check(self.listing(), strict=False)
        if same is not None and region == same:
            # only comments, labels or spelling differ: the same code, so nothing to rewrite (a
            # rewrite would still move the scene within a bank in the game's original layout)
            self.set_msg("no change: the listing assembles to the same code as the scene")
            return False
        entry = app.scene.entry_pc
        box = {}
        before = bytes(app.bank.data)
        ok = app.apply("Rewrite scene @0x%04x" % entry,
                       lambda: box.update(base=app.doc.container.rewrite_scene(app.bank, entry, text,
                                                                               strict=False)))
        if ok and bytes(app.bank.data) == before:
            # the relink is byte-exact: a listing that only differs in comments, labels or
            # spelling rebuilds the same bank (and leaves no undo step)
            self.load(force=True)
            self.set_msg("no change: the listing assembles to the same code as the scene")
            return False
        if ok:
            self.load(force=True)
            self.set_msg("applied: the bank was rebuilt with the new body in place; the scene now "
                         "starts at 0x%04x" % box.get("base", 0), "ok")
        return ok

    def toggle_help(self):
        if self._help:
            self.help.pack_forget()
        else:
            self.help.pack(fill="x", padx=4, pady=(0, 2), before=self.box)
        self._help = not self._help


# --------------------------------------------------------------------------- #
def town_event_summary(doc, bank):
    """One paragraph for a town-event bank: its em.bin entry, what starts it, who takes part."""
    eid = subevents.entry_of_bank(bank.index)
    code = catalog.subevent_code(doc, eid)
    how = [subevents.describe_start(ty, r) for ty, r in subevents.starters(bank)]
    who = [n for _c, n in subevents.participants(doc.em, eid)] if doc.em is not None else []
    parts = ["Town event: em.bin entry #%d%s decides when it can be picked; at day change one "
             "eligible event is reserved for the next day" % (eid, " (EV_SUBEV_%s)" % code if code else "")]
    parts.append("starts (StartReservedSubEvent) by " + " or ".join(dict.fromkeys(how)) if how
                 else "no scene here starts it (StartReservedSubEvent), so it never runs")
    if who:
        parts.append("participants: %s -- companions among them go home when it is reserved"
                     % ", ".join(who))
    text = "; ".join(parts) + "."
    rule = subevents.special_rule(eid)
    if rule:
        text += "\n⚑ Special slot (%s): %s" % rule
    return text


class TriggersTab(ttk.Frame):
    """The bank's type table: which scenes the engine starts, for what, with which keys."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=2, pady=2)
        for text, cmd, tip in (
                ("New scene…", app.ask_new_scene, "Create a new scene in this bank: when it plays, its "
                                                  "keys and its body."),
                ("Open", self.open_selected, "Open the selected trigger's scene (double-click works too)."),
                ("Remove", self.remove, "Unregister the selected trigger: it stops firing; the "
                                        "scene's code stays as dead bytes.")):
            b = ttk.Button(bar, text=text, command=cmd)
            b.pack(side="left", padx=2)
            Tip(b, tip)
        self.lbl = ttk.Label(self, text="", anchor="w", font=("Segoe UI", 8), foreground="#0d5f8f",
                             wraplength=760, justify="left")
        self.lbl.pack(fill="x", padx=4)
        f = ttk.Frame(self)
        f.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(f)
        sb.pack(side="right", fill="y")
        self.tree = ttk.Treeview(f, columns=("pc", "keys"), yscrollcommand=sb.set, selectmode="browse")
        self.tree.heading("#0", text="when it plays (trigger type) / trigger")
        self.tree.heading("pc", text="scene")
        self.tree.heading("keys", text="matches (keys; -1 = any where the type allows it)")
        self.tree.column("#0", width=280, stretch=False)
        self.tree.column("pc", width=90, stretch=False)
        self.tree.column("keys", width=420)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.config(command=self.tree.yview)
        self.tree.bind("<Double-Button-1>", lambda _e: self.open_selected())
        self.tree.bind("<Return>", lambda _e: self.open_selected())
        # the selected entry's keys go to the editor's right-hand pane (TriggerDetail)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: app.trigger_selected(*self.selected()))
        self.rows = {}
        self.bank_pos = None

    def show(self, pos):
        self.bank_pos = pos
        self.refresh()

    def refresh(self):
        t = self.tree
        typ0, r0 = self.selected()
        keep = (typ0, r0.index if r0 is not None else None) if typ0 is not None else None
        t.delete(*t.get_children())
        self.rows = {}
        app = self.app
        if self.bank_pos is None or app.doc.container is None:
            self.lbl.config(text="(open a bank to see what starts its scenes)")
            return
        bank = app.doc.container.banks[self.bank_pos]
        try:
            tt = bank.type_table_full()
        except Exception as e:
            self.lbl.config(text="type table unreadable (%s)" % err_text(e))
            return
        total = 0
        starts = set()
        if subevents.is_subevent_bank(bank):    # which entries run StartReservedSubEvent
            starts = {(ty, r.index) for ty, r in subevents.starters(bank)}
        for typ, (cnt, _off) in tt.items():
            note = ""
            try:
                recs = bank.entry_records(typ)
            except script.ScriptError as e:
                recs, note = [], "  [%s]" % e
            node = t.insert("", "end", text="%s  (%d)%s" % (catalog.type_label(typ), cnt, note),
                            values=("", catalog.type_summary(typ)), open=True)
            self.rows[node] = (typ, None)
            for r in recs:
                dead = "" if script.decode_statement(bank.data, r.event_id) else "  [no code]"
                keys = catalog.describe_keys(typ, r.subs)
                if (typ, r.index) in starts:
                    keys = "▶ starts the town event · " + keys
                iid = t.insert(node, "end", text="  #%d" % r.index, values=("@%04x%s" % (r.event_id, dead), keys))
                self.rows[iid] = (typ, r)
                total += 1
        if keep is not None:                    # the same row again after an edit
            for iid, (ty, r) in self.rows.items():
                if ty == keep[0] and (r.index if r is not None else None) == keep[1]:
                    t.selection_set(iid)
                    t.see(iid)
                    break
        app.trigger_selected(*self.selected())
        text = ("%s: %d trigger type%s, %d trigger%s%s"
                % (catalog.bank_title(bank), len(tt), "" if len(tt) == 1 else "s", total,
                   "" if total == 1 else "s",
                   "   · empty — New scene… registers the first one" if not tt else ""))
        if subevents.is_subevent_bank(bank):
            text += "\n" + town_event_summary(app.doc, bank)
        self.lbl.config(text=text)

    def selected(self):
        s = self.tree.selection()
        return self.rows.get(s[0], (None, None)) if s else (None, None)

    def open_selected(self):
        _t, r = self.selected()
        if r is None:
            self.app.status("select a trigger row (not the type) to open its scene")
            return False
        self.app.open_scene(self.bank_pos, r.event_id, tab="Script")
        return True

    def remove(self):
        typ, r = self.selected()
        if r is None:
            self.app.status("select a trigger row to remove it")
            return False
        from tkinter import messagebox
        if not messagebox.askyesno("Remove trigger", "Unregister %s trigger #%d (scene @%04x)?\nIt "
                                   "stops firing; the scene's code stays in the bank."
                                   % (catalog.type_label(typ), r.index, r.event_id)):
            return False
        return self.app.remove_entry(self.bank_pos, typ, r.index)


class TriggerDetail(ttk.Frame):
    """The editor's right-hand pane while the Triggers tab is open (it takes the Inspector's
    place): what the selected entry's type does, and one
    named field per key (entry_types' key specs). A trigger box (x1 y1 x2 y2) shows as x, y,
    width, height with 'Draw on map'; a condition picks an em.bin entry; a map key picks a
    map. Apply (or Enter) writes the keys back, keeping each key's tag."""

    BOX = ("x1", "y1", "x2", "y2")

    def __init__(self, parent, app, tab):
        super().__init__(parent)
        self.app, self.tab = app, tab
        self.sf = ScrollFrame(self)
        self.sf.pack(fill="both", expand=True)
        self.body = self.sf.body
        self.typ = self.rec = None
        self.fields = []                    # [(kind, key index | box, StringVar, token map)]
        self.show(None, None)

    # ---- layout ------------------------------------------------------------------ #
    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()
        self.fields = []

    def _label(self, text, **kw):
        kw.setdefault("wraplength", 330)
        kw.setdefault("justify", "left")
        lb = ttk.Label(self.body, text=text, **kw)
        lb.pack(anchor="w", padx=8, pady=(2, 0))
        return lb

    def show(self, typ, rec):
        self._clear()
        self.typ, self.rec = typ, rec
        if typ is None:
            self._label("Select a trigger type or a trigger on the left.", foreground="#777")
            return
        self._label(catalog.type_label(typ), font=("Segoe UI", 10, "bold"))
        summ = catalog.type_summary(typ)
        if summ:
            self._label(summ, foreground="#444")
        if rec is None:
            recipe = catalog.type_recipe(typ)
            if recipe:
                self._label(recipe, foreground="#2a6a8a", font=("Segoe UI", 8))
            self._label("Select one of its triggers to edit its keys.", foreground="#777")
            return
        head = ttk.Frame(self.body)
        head.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Label(head, text="trigger #%d → scene @%04x" % (rec.index, rec.event_id)).pack(side="left")
        ttk.Button(head, text="Open scene", command=self.tab.open_selected).pack(side="right")
        box = ttk.LabelFrame(self.body, text="Keys (what this trigger matches)", padding=6)
        box.pack(fill="x", padx=6, pady=6)
        box.columnconfigure(1, weight=1)
        self._build_fields(box, typ, rec)
        self.warn = ttk.Label(self.body, foreground="#b06000", wraplength=330, justify="left")
        self.warn.pack(anchor="w", padx=8)
        bb = ttk.Frame(self.body)
        bb.pack(fill="x", padx=6, pady=6)
        ap = ttk.Button(bb, text="Apply", command=self.apply)
        ap.pack(side="left")
        Tip(ap, "Write these keys into the trigger (Enter in a field does the same). Undo with Ctrl+Z.")
        ttk.Button(bb, text="Revert", command=lambda: self.show(self.typ, self.rec)).pack(side="left", padx=4)
        self._check()

    def _spec(self, typ, k):
        try:
            from rf4s_modkit import entry_types
            return entry_types.key_spec(typ, k) or {}
        except Exception:
            return {}

    def _row(self, box, r, label, var, hint, options=None, width=12):
        ttk.Label(box, text=label).grid(row=r, column=0, sticky="nw", padx=(0, 6), pady=2)
        if options:
            w = FilterCombo(box, [d for d, _t in options], on_pick=lambda _t: self._check(), width=30,
                            textvariable=var)
        else:
            w = ttk.Entry(box, textvariable=var, width=width)
        w.grid(row=r, column=1, sticky="w", pady=2)
        w.bind("<Return>", lambda _e: self.apply())
        var.trace_add("write", lambda *_a: self._check())
        if hint:
            ttk.Label(box, text=hint, foreground="#777", font=("Segoe UI", 8), wraplength=320,
                      justify="left").grid(row=r + 1, column=0, columnspan=3, sticky="w", pady=(0, 3))
        return w

    def _build_fields(self, box, typ, rec):
        subs = list(rec.subs)
        vals = [v for _t, v in subs]
        names = [(self._spec(typ, k).get("name") or "key %d" % k) for k in range(len(subs))]
        row = 0
        bi = [names.index(n) for n in self.BOX] if all(n in names for n in self.BOX) else None
        if bi:
            x1, y1, x2, y2 = (vals[i] for i in bi)
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)
            vars_ = [tk.StringVar(value=str(v)) for v in (x1, y1, x2 - x1, y2 - y1)]
            for lab, var, hint in zip(("x", "y", "width", "height"), vars_, (
                    "box left edge (1/8-tile units, like positions)", "box top edge", "", "")):
                self._row(box, row, lab, var, hint)
                row += 2
            self.fields.append(("box", tuple(bi), vars_, None))
            b = ttk.Button(box, text="📍 Draw the box on the map…", command=self.draw_box)
            b.grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 6))
            Tip(b, "Drag the trigger area on the map (1/8-tile units; the map is this bank's map, "
                   "or the trigger's map key).")
            row += 1
        for k, (tag, v) in enumerate(subs):
            if bi and k in bi:
                continue
            spec = self._spec(typ, k)
            name = names[k]
            from . import argspec as _argspec
            hint = _argspec.clean_help(spec.get("meaning") or "")
            if len(hint) > 220:
                hint = hint[:219].rstrip() + "…"
            if spec.get("wildcard"):
                hint = "-1 = any. " + hint
            opts = self._key_options(name)
            var = tk.StringVar()
            tokmap = dict(opts) if opts else None
            disp = next((d for d, t in opts if t == str(v)), str(v)) if opts else str(v)
            var.set(disp)
            self._row(box, row, name, var, hint, opts)
            self.fields.append(("key", k, var, tokmap))
            row += 2

    def _key_options(self, name):
        """[(display, token)] picker values for a key named `name`, or None."""
        n = name.lower()
        if n == "condition":
            em = self.app.doc.em
            if em is None:
                return None
            try:
                from rf4s_modkit import emtext
            except ImportError:
                emtext = None
            out = [("-1  (none / any)", "-1"), ("0  (none)", "0")]
            for i in range(len(em.entries)):
                nm = em.names.entry_name(i) or ""
                txt = (emtext.entry_text(nm) if emtext else "") or ""
                out.append(("%d  %s%s" % (i, nm, ("  — " + txt) if txt else ""), str(i)))
            return out
        if n == "map":
            from . import toolbox
            return [(d, str(script.map_leaf_value(t[4:-1]))) for d, t in toolbox.map_choices()]
        return None

    # ---- values ------------------------------------------------------------------ #
    def values(self):
        """The entry's keys as the fields say: [(tag, value)] (raises ValueError)."""
        subs = list(self.rec.subs)
        out = [v for _t, v in subs]
        for kind, where, var, tokmap in self.fields:
            if kind == "box":
                x, y, w, h = (int(v.get().strip(), 0) for v in var)
                if w < 0 or h < 0:
                    raise ValueError("width and height must be 0 or more")
                for i, val in zip(where, (x, y, x + w, y + h)):
                    out[i] = val
            else:
                t = var.get().strip()
                t = (tokmap or {}).get(t, t)
                tok = t.split()[0] if t else ""
                try:
                    out[where] = int(tok, 0)
                except ValueError:
                    raise ValueError("%s: %r is not a number" % (self._spec(self.typ, where).get("name")
                                                                   or "key %d" % where, t))
        return [(tag, v) for (tag, _o), v in zip(subs, out)]

    def _check(self):
        if self.rec is None or not hasattr(self, "warn"):
            return
        try:
            keys = self.values()
        except ValueError as e:
            self.warn.config(text="✗ " + err_text(e), foreground="#b00")
            return
        changed = keys != [(t, v) for t, v in self.rec.subs]
        if changed:                     # keys that cannot work are refused on Apply: say so now
            clash, more, _w = self.app.doc.container.entry_key_conflicts(
                self.tab.bank_pos, self.typ, keys, editing=self.rec.index)
            if clash:
                self.warn.config(text="✗ " + clash, foreground="#b00")
                return
        else:
            more = []
        probs = catalog.key_problems(self.typ, keys, self.app.doc.em) + more
        self.warn.config(text=("⚠ " + "; ".join(probs)) if probs else ("● not applied yet" if changed else ""),
                         foreground="#b06000")

    def apply(self):
        if self.rec is None:
            return False
        try:
            keys = self.values()
        except ValueError as e:
            self.warn.config(text="✗ " + err_text(e), foreground="#b00")
            return False
        if keys == [(t, v) for t, v in self.rec.subs]:
            return True
        return self.app.set_entry_keys(self.tab.bank_pos, self.typ, self.rec.index, keys)

    def draw_box(self):
        from . import toolbox
        box_field = next((f for f in self.fields if f[0] == "box"), None)
        if box_field is None:
            return None
        try:
            x, y, w, h = (int(v.get().strip(), 0) for v in box_field[2])
            cur = (x, y, x + w, y + h)
        except ValueError:
            cur = None
        bank = self.app.doc.container.banks[self.tab.bank_pos]
        mid, lock, note = None, None, None
        mapf = next((f for f in self.fields if f[0] == "key"
                     and (self._spec(self.typ, f[1]).get("name") or "") == "map"), None)
        if mapf is not None:
            t = mapf[2].get().strip()
            try:
                mid = int((mapf[3] or {}).get(t, t).split()[0], 0)
                lock = "the trigger's map key says which map the box is on"
            except (ValueError, IndexError):
                note = "the trigger's map key is not a map: choose one"
        elif bank.kind == "tail":
            mid, lock = bank.index, "the trigger is in this map's event bank"
        else:
            note = "this bank is not tied to one map: choose the map the trigger is for"

        def done(x1, y1, x2, y2, _mid):
            for v, val in zip(box_field[2], (x1, y1, x2 - x1, y2 - y1)):
                v.set(str(val))
            if mapf is not None and lock is None and _mid is not None:    # the map was chosen here
                mapf[2].set(next((d for d, t in (mapf[3] or {}).items() if t == str(_mid)), str(_mid)))
        self._box_picker = toolbox.MapBoxPicker(self, mid, cur, done, lock=lock, note=note)
        return self._box_picker


# --------------------------------------------------------------------------- #
class OverviewTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        sb = ttk.Scrollbar(self)
        sb.pack(side="right", fill="y")
        self.text = tk.Text(self, wrap="word", font=("Consolas", 9), state="disabled",
                            yscrollcommand=sb.set, **DARK)
        self.text.pack(side="left", fill="both", expand=True)
        sb.config(command=self.text.yview)
        for tag, col in (("h", "#ffd479"), ("h1", "#ffd479"), ("k", "#9a9aa6"), ("dlg", "#86d0ff"),
                         ("emf", "#7fd6a0"), ("flag", "#e08fd0"), ("warn", "#e0a060")):
            self.text.tag_configure(tag, foreground=col)
        self.text.tag_configure("h1", font=("Consolas", 10, "bold"))

    def render(self):
        app = self.app
        t = self.text
        t.config(state="normal")
        t.delete("1.0", "end")
        if app.scene is not None:
            for s, tag in SceneText(app.doc, app.bank, app.scene).overview():
                t.insert("end", s, tag or ())
        t.config(state="disabled")

