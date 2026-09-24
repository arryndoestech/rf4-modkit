"""The Source, Triggers and Overview tabs."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from guiutil import Tip
from rf4s_modkit import script, scriptasm

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
                ("Apply to scene", self.apply, "Assemble and make the scene play this listing (the "
                                               "new body is appended; the scene's entry jumps to it)."),
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
        self.text = tk.Text(self.box, wrap="none", font=("Consolas", 10), undo=True,
                            yscrollcommand=sb.set, **DARK)
        self.text.pack(side="left", fill="both", expand=True)
        sb.config(command=self.text.yview)
        self.text.tag_configure("err", background="#5a1a1a")
        self.text.tag_configure("cmt", foreground="#7c8c7c")
        self._key = None

    def set_msg(self, s, kind="info"):
        self.msg.config(text=s, foreground={"ok": "#1d7a3a", "err": "#b02020"}.get(kind, "#0d5f8f"))

    def listing(self):
        """The scene as a re-assemblable listing; a leading JMP to the very next label (left
        by an earlier Apply) is dropped so round trips don't stack trampolines."""
        app = self.app
        txt = scriptasm.scene_listing(app.scene, app.bank, dialog=app.doc.text, bank_no=app.bank_pos)
        lines = txt.split("\n")
        for i, ln in enumerate(lines):
            s = ln.strip()
            if not s or s.startswith(";"):
                continue
            m = re.match(r"^(?:[0-9a-fA-F]{4}:\s*)?JMP\s+([A-Za-z_]\w*)\s*(?:;.*)?$", s)
            if m:
                nxt = next((l2.strip() for l2 in lines[i + 1:] if l2.strip()), "")
                if nxt == m.group(1) + ":":
                    del lines[i]
            break
        return "\n".join(lines)

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
        body = self.listing()
        self.text.insert("1.0", body)
        for n, ln in enumerate(body.split("\n"), 1):
            c = ln.find(";")
            if c >= 0:
                self.text.tag_add("cmt", "%d.%d" % (n, c), "%d.end" % n)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self._key = key
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
        region, labels, err = app.assemble_check(text)
        if err:
            self.mark_error(err)
            self.set_msg("error: " + err, "err")
            return None
        self.text.tag_remove("err", "1.0", "end")
        n = count_statements(text)
        self.set_msg("OK — %d statement%s assemble to %d bytes; Apply to scene applies it"
                     % (n, "" if n == 1 else "s", len(region)), "ok")
        return region

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
        region, _l, err = app.assemble_check(text)
        if err:
            self.mark_error(err)
            self.set_msg("error: " + err, "err")
            return False
        entry = app.scene.entry_pc
        box = {}
        ok = app.apply("Rewrite scene @0x%04x" % entry,
                       lambda: box.update(base=app.doc.container.rewrite_scene(app.bank, entry, text)))
        if ok:
            self.load(force=True)
            self.set_msg("applied: %d bytes at 0x%04x; the scene's entry now jumps there"
                         % (len(region), box.get("base", 0)), "ok")
        return ok

    def toggle_help(self):
        if self._help:
            self.help.pack_forget()
        else:
            self.help.pack(fill="x", padx=4, pady=(0, 2), before=self.box)
        self._help = not self._help


# --------------------------------------------------------------------------- #
class TriggersTab(ttk.Frame):
    """The bank's type table: which scenes the engine starts, for what, with which keys."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=2, pady=2)
        for text, cmd, tip in (
                ("New scene…", app.ask_new_scene, "Mint a brand-new scene in this bank: pick WHEN it "
                                                  "plays (the action type), its keys, and write its body."),
                ("Open", self.open_selected, "Open the selected entry's scene (double-click works too)."),
                ("Change keys…", self.rekey, "Change what the selected entry matches (its keys; -1 = any)."),
                ("Remove", self.remove, "Unregister the selected entry: its trigger stops firing; the "
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
        self.tree.heading("#0", text="when it plays (action type) / entry")
        self.tree.heading("pc", text="scene")
        self.tree.heading("keys", text="matches (keys; -1 = any)")
        self.tree.column("#0", width=280, stretch=False)
        self.tree.column("pc", width=90, stretch=False)
        self.tree.column("keys", width=420)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.config(command=self.tree.yview)
        self.tree.bind("<Double-Button-1>", lambda _e: self.open_selected())
        self.tree.bind("<Return>", lambda _e: self.open_selected())
        self.rows = {}
        self.bank_pos = None

    def show(self, pos):
        self.bank_pos = pos
        self.refresh()

    def refresh(self):
        t = self.tree
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
            self.lbl.config(text="type table unreadable (%s)" % e)
            return
        total = 0
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
                iid = t.insert(node, "end", text="  #%d" % r.index,
                               values=("@%04x%s" % (r.event_id, dead), catalog.describe_keys(typ, r.subs)))
                self.rows[iid] = (typ, r)
                total += 1
        self.lbl.config(text="%s: %d action type%s, %d entr%s%s"
                             % (catalog.bank_title(bank), len(tt), "" if len(tt) == 1 else "s", total,
                                "y" if total == 1 else "ies",
                                "   · empty — New scene… registers the first one" if not tt else ""))

    def selected(self):
        s = self.tree.selection()
        return self.rows.get(s[0], (None, None)) if s else (None, None)

    def open_selected(self):
        _t, r = self.selected()
        if r is None:
            self.app.status("select an entry row (not the type) to open its scene")
            return False
        self.app.open_scene(self.bank_pos, r.event_id, tab="Script")
        return True

    def rekey(self):
        typ, r = self.selected()
        if r is None:
            self.app.status("select an entry row to change its keys")
            return False
        from tkinter import simpledialog
        s = simpledialog.askstring(
            "Change keys", "Keys for %s entry #%d — a comma list: `5, -1` (-1 = any) or `(tag, value)` "
            "pairs for a non-1 tag:" % (catalog.type_label(typ), r.index),
            initialvalue=catalog.entry_keys_text(r.subs), parent=self)
        if s is None:
            return False
        return self.app.set_entry_keys(self.bank_pos, typ, r.index, s)

    def remove(self):
        typ, r = self.selected()
        if r is None:
            self.app.status("select an entry row to remove it")
            return False
        from tkinter import messagebox
        if not messagebox.askyesno("Remove trigger", "Unregister %s entry #%d (scene @%04x)?\nIts trigger "
                                   "stops firing; the scene's code stays in the bank."
                                   % (catalog.type_label(typ), r.index, r.event_id)):
            return False
        return self.app.remove_entry(self.bank_pos, typ, r.index)


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

