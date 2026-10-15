"""The Translations window: a scene's / bank's / every scene's dialogue lines in a source and a
target language, with what needs work (rf4s_modkit.translate), edited in place, and CSV for
translators."""
from __future__ import annotations

import pathlib
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from guiutil import Tip
from rf4s_modkit import script, textlint, translate

from .catalog import LOCALES, bank_title

SCOPES = ("This scene", "This bank", "Every scene in rf3.mc")
SHOW = ("Needs work", "Everything")


class TranslateWindow:
    def __init__(self, app):
        self.app = app
        self._orig = {}                         # locale -> original TextArchive | False
        self.rows = []
        self.cur = None
        w = self.win = tk.Toplevel(app.frame)
        w.title("Translations")
        w.geometry("1100x680")
        top = ttk.Frame(w, padding=6)
        top.pack(fill="x")
        locs = [loc for loc in LOCALES if app.doc.archive(loc) is not None] or [app.doc.locale]
        ttk.Label(top, text="From").pack(side="left")
        self.src = tk.StringVar(value="eng" if "eng" in locs else locs[0])
        ttk.Combobox(top, textvariable=self.src, values=locs, state="readonly", width=5).pack(side="left", padx=4)
        ttk.Label(top, text="to").pack(side="left")
        tgt0 = app.doc.locale if app.doc.locale != self.src.get() else next(
            (x for x in locs if x != self.src.get()), locs[0])
        self.tgt = tk.StringVar(value=tgt0)
        ttk.Combobox(top, textvariable=self.tgt, values=locs, state="readonly", width=5).pack(side="left", padx=4)
        ttk.Label(top, text="Lines of").pack(side="left", padx=(12, 0))
        self.scope = tk.StringVar(value=SCOPES[0])
        ttk.Combobox(top, textvariable=self.scope, values=SCOPES, state="readonly", width=20).pack(side="left", padx=4)
        self.show = tk.StringVar(value=SHOW[0])
        ttk.Combobox(top, textvariable=self.show, values=SHOW, state="readonly", width=12).pack(side="left", padx=4)
        for v in (self.src, self.tgt, self.scope, self.show):
            v.trace_add("write", lambda *_a: self.refresh())
        self.count = ttk.Label(top, foreground="#666")
        self.count.pack(side="left", padx=10)
        eb = ttk.Button(top, text="Export CSV…", command=self.export)
        eb.pack(side="right")
        ib = ttk.Button(top, text="Import CSV…", command=self.import_)
        ib.pack(side="right", padx=4)
        Tip(eb, "The listed lines as a spreadsheet for a translator: id, where it is used, source, "
                "target, what needs work.")
        Tip(ib, "Read a translated CSV back: every changed line goes into the target language as one "
                "undo step; lines the game would mishandle are listed and left out.")
        pw = ttk.PanedWindow(w, orient="vertical")
        pw.pack(fill="both", expand=True, padx=6)
        tf = ttk.Frame(pw)
        self.tree = ttk.Treeview(tf, columns=("id", "src", "tgt", "state"), show="headings", selectmode="browse")
        for col, txt, wd in (("id", "line", 70), ("src", "source", 380), ("tgt", "target", 380), ("state", "needs", 200)):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=wd, stretch=col in ("src", "tgt"))
        sb = ttk.Scrollbar(tf, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._pick())
        pw.add(tf, weight=3)
        ef = ttk.Frame(pw, padding=(0, 6))
        self.where = ttk.Label(ef, foreground="#666")
        self.where.pack(anchor="w")
        self.src_txt = tk.Text(ef, height=4, wrap="word", font=("Segoe UI", 10), state="disabled", bg="#f4f4f6")
        self.src_txt.pack(fill="x")
        self.tgt_txt = tk.Text(ef, height=4, wrap="word", font=("Segoe UI", 10), undo=True)
        self.tgt_txt.pack(fill="x", pady=(4, 0))
        self.note = ttk.Label(ef, foreground="#b06000", wraplength=1000, justify="left")
        self.note.pack(anchor="w")
        bb = ttk.Frame(ef)
        bb.pack(fill="x", pady=(4, 0))
        ab = ttk.Button(bb, text="Apply  (Ctrl+Enter)", command=self.apply)
        ab.pack(side="left")
        ttk.Button(bb, text="Copy source", command=self._copy_source).pack(side="left", padx=4)
        nb = ttk.Button(bb, text="Next to do  (Ctrl+Down)", command=self.next_todo)
        nb.pack(side="left")
        Tip(ab, "Write this text into the target language (one undo step in the editor). The same "
                "checks as any line edit run first.")
        pw.add(ef, weight=1)
        self.tgt_txt.bind("<Control-Return>", lambda _e: (self.apply(), "break")[1])
        w.bind("<Control-Down>", lambda _e: (self.next_todo(), "break")[1])
        w.bind("<Escape>", lambda _e: w.destroy())
        self.refresh()

    # ---- data ------------------------------------------------------------------------- #
    def _orig_arc(self, loc):
        """The original game's rf3mc.<loc> (the toolkit's backup of it), or None."""
        if loc not in self._orig:
            arc = None
            try:
                from rf4s_modkit import gamepaths, textdb
                t = gamepaths.game_targets(["rf3mc.%s" % loc]) or {}
                p = t.get("rf3mc.%s" % loc)
                o = gamepaths.backup_path(p) if p is not None else None
                if o is not None and pathlib.Path(o).is_file():
                    arc = textdb.TextArchive.load(o)
            except Exception:  # noqa: BLE001 -- no originals: every identical line counts
                arc = None
            self._orig[loc] = arc or False
        return self._orig[loc] or None

    @staticmethod
    def _getter(arc):
        def get(lid):
            if arc is None or lid is None or lid >= len(arc):
                return None
            try:
                return arc.text(lid)
            except Exception:  # noqa: BLE001
                return None
        return get

    def _ids(self):
        """(ids, {id: where}) of the chosen scope."""
        app = self.app
        scope = self.scope.get()
        where = {}
        if scope == SCOPES[0]:
            if app.scene is None:
                return [], where
            ids = translate.scene_line_ids(app.scene.stmts.values())
            for i in ids:
                where[i] = "scene @%04x" % app.scene.entry_pc
            return ids, where
        c = app.doc.container
        banks = [app.bank_pos] if scope == SCOPES[1] else range(len(c.banks))
        ids = []
        for bi in banks:
            if bi is None:
                continue
            b = c.banks[bi]
            if len(b.data) <= 296:
                continue
            for sc in script.disassemble_bank(b):
                for i in translate.scene_line_ids(sc.stmts.values()):
                    if i not in where:
                        where[i] = "%s @%04x" % (bank_title(b), sc.entry_pc)
                        ids.append(i)
        return ids, where

    def refresh(self):
        app = self.app
        src, tgt = self.src.get(), self.tgt.get()
        try:
            self.win.config(cursor="watch")
            self.win.update_idletasks()
        except tk.TclError:
            return
        ids, where = self._ids()
        os_, ot = self._orig_arc(src), self._orig_arc(tgt)
        self.rows = translate.rows(ids, self._getter(app.doc.archive(src)), self._getter(app.doc.archive(tgt)),
                                   where, self._getter(os_) if os_ and ot else None,
                                   self._getter(ot) if os_ and ot else None)
        todo = sum(1 for r in self.rows if r[4])
        shown = [r for r in self.rows if r[4]] if self.show.get() == SHOW[0] else self.rows
        self.tree.delete(*self.tree.get_children())
        for lid, _w, s, t, states in shown:
            self.tree.insert("", "end", iid=str(lid), values=(
                lid, " ".join((s or "").split())[:90], "" if t is None else " ".join(t.split())[:90],
                ", ".join(translate.STATE_TEXT[k] for k, _m in states)))
        self.count.config(text="%d line(s), %d need work%s" % (len(self.rows), todo,
                          "" if (os_ and ot) else "  (no original files: identical lines all count)"))
        self.win.config(cursor="")
        if self.cur is not None and self.tree.exists(str(self.cur)):
            self.tree.selection_set(str(self.cur))
            self.tree.see(str(self.cur))

    # ---- editing ----------------------------------------------------------------------- #
    def _row(self, lid):
        return next((r for r in self.rows if r[0] == lid), None)

    def _pick(self):
        sel = self.tree.selection()
        if not sel:
            return
        lid = int(sel[0])
        self.cur = lid
        r = self._row(lid)
        if r is None:
            return
        _lid, where, s, t, states = r
        self.where.config(text="line #%d · used in %s · %s → %s" % (lid, where or "?", self.src.get(), self.tgt.get()))
        self.src_txt.config(state="normal")
        self.src_txt.delete("1.0", "end")
        self.src_txt.insert("1.0", s or "")
        self.src_txt.config(state="disabled")
        self.tgt_txt.delete("1.0", "end")
        self.tgt_txt.insert("1.0", t or "")
        self.note.config(text="\n".join(m for _k, m in states))

    def _copy_source(self):
        txt = self.src_txt.get("1.0", "end-1c")
        self.tgt_txt.delete("1.0", "end")
        self.tgt_txt.insert("1.0", txt)

    def apply(self):
        if self.cur is None:
            return False
        text = self.tgt_txt.get("1.0", "end-1c")
        ok = self.app.set_text_in(self.tgt.get(), self.cur, text)
        if ok:
            self.refresh()
        return ok

    def next_todo(self):
        kids = self.tree.get_children()
        if not kids:
            return None
        ids = [int(k) for k in kids]
        todo = [i for i in ids if (self._row(i) or (0, 0, 0, 0, []))[4]]
        if not todo:
            return None
        after = [i for i in todo if self.cur is None or ids.index(i) > (ids.index(self.cur) if self.cur in ids else -1)]
        nxt = (after or todo)[0]
        self.tree.selection_set(str(nxt))
        self.tree.see(str(nxt))
        self.tgt_txt.focus_set()
        return nxt

    # ---- CSV ------------------------------------------------------------------------------ #
    def export(self, path=None):
        rows = [r for r in self.rows if r[4]] if self.show.get() == SHOW[0] else self.rows
        if path is None:
            path = filedialog.asksaveasfilename(parent=self.win, defaultextension=".csv",
                                                initialfile="lines_%s_to_%s.csv" % (self.src.get(), self.tgt.get()),
                                                filetypes=[("CSV", "*.csv")])
        if not path:
            return None
        pathlib.Path(path).write_text(translate.export_csv(rows, self.src.get(), self.tgt.get()),
                                      encoding="utf-8", newline="")
        self.app.status("Exported %d line(s) to %s" % (len(rows), path))
        return path

    def import_(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(parent=self.win, filetypes=[("CSV", "*.csv"), ("All", "*.*")])
        if not path:
            return None
        try:
            got = translate.read_csv(pathlib.Path(path).read_text(encoding="utf-8-sig"), self.tgt.get())
        except (OSError, ValueError) as e:
            messagebox.showerror("Import CSV", str(e), parent=self.win)
            return None
        arc = self.app.doc.archive(self.tgt.get())
        get = self._getter(arc)
        changes, refused = {}, []
        for lid, text in sorted(got.items()):
            if get(lid) == text:
                continue
            errs = textlint.errors(text)
            if errs:
                refused.append("#%d: %s" % (lid, textlint.format_issues(errs, 2)))
                continue
            changes[lid] = text
        n = self.app.set_texts_in(self.tgt.get(), changes, "Import %d translation(s) (%s)" % (len(changes), self.tgt.get())) \
            if changes else 0
        self.refresh()
        msg = "%d line(s) changed in rf3mc.%s." % (n, self.tgt.get())
        if refused:
            msg += "\n\nLeft out (the game would mishandle them):\n" + "\n".join(refused[:20]) + (
                "\n(+%d more)" % (len(refused) - 20) if len(refused) > 20 else "")
        messagebox.showinfo("Import CSV", msg, parent=self.win)
        return n, refused
