"""text_tab.py -- the asset explorer's editor for the game's text files.

Two kinds of file, one editor:
  * TEXT archives (magic `TEXT`): every rf3Txt* / rf4Txt* file (item, character, map, quest,
    shop, menu, calendar ... names and descriptions) and the cutscene dialogue rf3mc.<locale>.
    A line is addressed by its number (the id the game and the scripts use), so lines can be
    changed and added at the end, never removed or moved.
  * `.strings` files (Localization-<lang>.strings): the PC version's menu and option text,
    "key" = "value"; keys can be added and removed.

A line is checked the way the game will read it (rf4s_modkit.textlint) while it is typed: a
line the game could crash on cannot be applied. Characters that can't be typed or seen (the
colour and shift control bytes, the button icons) are shown and typed as backslash escapes
(rf4s_modkit.textesc: \\red, \\btn(a) ...); the Insert menu lists them and the ＠ codes. *Save* writes the file where the game loads it
(Bundle\\00_mods when the game only has it packed; the original is kept in ModdingBackup
once), or back to the file it was opened from; *Save as…* writes anywhere. Names the other
editors show (characters, items, maps, skills) follow a saved name file by themselves.
"""
from __future__ import annotations

import pathlib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from rf4s_modkit import gamepaths, strings_file, textdb, textesc, textlint

MAX_ROWS = 5000


class _Model:
    """A text file as ordered (key, text) rows. TEXT: key = the line number."""

    def __init__(self, name, data):
        self.name = name
        self.is_text = data[:4] == b"TEXT"
        if self.is_text:
            self.arc = textdb.TextArchive.parse(data)
            self.rows = {i: self._decode(i) for i in range(len(self.arc.entries))}
        else:
            self.rows = dict(strings_file.parse(data.decode("utf-8")))
        self.original = dict(self.rows)

    def _decode(self, i):
        return self.arc.entries[i].decode("utf-8", "replace")

    def set(self, key, value):
        if self.is_text:
            self.arc.set_text(key, value)
        self.rows[key] = value

    def add(self, key=None, value=""):
        if self.is_text:
            key = self.arc.append_text(value)
        elif not key or key in self.rows:
            raise ValueError("a new key needs a name that is not used yet")
        self.rows[key] = value
        return key

    def remove(self, key):
        if self.is_text:
            raise ValueError("lines of a TEXT file cannot be removed: the scripts address them by number")
        del self.rows[key]

    def changed(self, key):
        return self.original.get(key) != self.rows.get(key)

    def build(self):
        if self.is_text:
            return self.arc.build()
        return strings_file.dumps(self.rows).encode("utf-8")


def problems(text):
    """textlint issues worth showing (errors and warnings) of a game text."""
    return [x for x in textlint.lint(text) if x.level in ("error", "warning")]


def shown(text):
    """A game text as the editors show it: the notation, one row (⏎ for line breaks)."""
    return textesc.to_edit(text).replace("\n", "⏎")


def insert_codes():
    """[(menu, [(label, code)])] for the Insert menu: the escapes, then the ＠ codes."""
    esc = dict(textesc.reference())
    colour = [("＋blue＋  (markup: blue between two ＋)", "＋＋"), ("／red／  (markup: red between two ／)", "／／")]
    colour += [("%s  %s" % (k, esc[k]), k) for k in (textesc.BS + "red", textesc.BS + "blue",
                                                     textesc.BS + "normal", textesc.BS + "rgb(255,128,1)")]
    shift = [("%s  %s" % (k, esc[k]), k) for k in (textesc.BS + "up", textesc.BS + "down",
                                                   textesc.BS + "shift(4)", textesc.BS + "base")]
    buttons = [("%s  %s" % (k, k[5:-1]), k) for k, _d in textesc.reference() if k.startswith(textesc.BS + "btn(")]
    values, names, other = [], [], []
    for code, group, what, setby, kind in textlint.token_reference():
        if not code.startswith(textlint.AT):
            continue
        ins = code.replace("<n>", "０")
        label = "%s  %s%s" % (ins, what[:70], ("  (slot set by %s)" % setby) if setby else "")
        if kind is not None and group in ("number", "things") or group == "number":
            values.append((label, ins))
        elif group == "people":
            names.append((label, ins))
        else:
            other.append((label, ins))
    return [("Colour", colour), ("Raise / lower", shift), ("Button icon", buttons),
            ("Value set by the script", values), ("Name", names), ("Other codes", other),
            ("", [(textesc.BS + textesc.BS + "  a backslash", textesc.BS + textesc.BS),
                  (textesc.BS + "u(E0A8)  any character by its code", textesc.BS + "u(E0A8)")])]


def insert_menu(parent, text_widget, after=None):
    """An 'Insert ▾' button whose menu puts an escape or ＠ code at the text box's cursor."""
    mb = ttk.Menubutton(parent, text="Insert ▾")
    menu = tk.Menu(mb, tearoff=False)
    mb["menu"] = menu

    def put(code):
        text_widget.insert("insert", code)
        if code in ("＋＋", "／／"):                     # the cursor between the two marks
            text_widget.mark_set("insert", "insert-1c")
        text_widget.focus_set()
        if after:
            after()
    for title, items in insert_codes():
        target = menu
        if title:
            target = tk.Menu(menu, tearoff=False)
            menu.add_cascade(label=title, menu=target)
        else:
            menu.add_separator()
        for label, code in items:
            target.add_command(label=label, command=lambda c=code: put(c))
    return mb


class TextTab:
    """The editor, built into `doc.content` of the explorer app `app`."""

    def __init__(self, app, doc, name, data):
        self.app, self.doc, self.name = app, doc, name
        self.m = _Model(name, data)
        self.sel = None
        self._build()
        self.refill()

    # ---- layout ---------------------------------------------------------------------- #
    def _build(self):
        from guiutil import Tip
        m, c = self.m, self.doc.content
        bar = ttk.Frame(c)
        bar.pack(fill="x", pady=(2, 2))
        sa = ttk.Button(bar, text="Save as…", command=self.save_as)      # right side first:
        sa.pack(side="right", padx=4)                                     # never squeezed out
        Tip(sa, "Write the file anywhere.")
        sv = ttk.Button(bar, text="Save", command=self.save)
        sv.pack(side="right", padx=2)
        Tip(sv, "Write the file where the game loads it (Bundle\\00_mods when the game has it only "
                "packed; the original is kept in ModdingBackup), or back to the file it was opened from.")
        self.count = ttk.Label(bar)
        self.count.pack(side="left", padx=6)
        ttk.Label(bar, text="Search:").pack(side="left")
        self.q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.q, width=24)
        e.pack(side="left", padx=2)
        Tip(e, "Shows the lines containing this text, or the line with this number / key.")
        ttk.Label(bar, text="Show:").pack(side="left", padx=(8, 0))
        self.only = tk.StringVar(value="all")
        cb = ttk.Combobox(bar, textvariable=self.only, state="readonly", width=13,
                          values=("all", "changed", "with problems"))
        cb.pack(side="left", padx=2)
        cb.bind("<<ComboboxSelected>>", lambda _e: self.refill())
        self.q.trace_add("write", lambda *_a: self.refill())

        pw = ttk.PanedWindow(c, orient="vertical")
        pw.pack(fill="both", expand=True)
        top = ttk.Frame(pw)
        cols = ("key", "text")
        self.tv = ttk.Treeview(top, columns=cols, show="headings", selectmode="browse")
        self.tv.heading("key", text="#" if m.is_text else "Key")
        self.tv.column("key", width=70 if m.is_text else 240, anchor="e" if m.is_text else "w", stretch=False)
        self.tv.heading("text", text="Text")
        self.tv.column("text", width=900)
        self.tv.tag_configure("changed", foreground="#1a5fb4")
        self.tv.tag_configure("problem", foreground="#b5471b")
        vs = ttk.Scrollbar(top, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.tv.pack(fill="both", expand=True)
        self.tv.bind("<<TreeviewSelect>>", self._on_select)
        pw.add(top, weight=4)

        ed = ttk.Frame(pw, padding=(6, 4))
        head = ttk.Frame(ed)
        head.pack(fill="x")
        if not m.is_text:
            self.del_btn = ttk.Button(head, text="Delete key", command=self.delete_key)
            self.del_btn.pack(side="right", padx=2)
        ab = ttk.Button(head, text="＋ New line" if m.is_text else "＋ New key…", command=self.new_row)
        ab.pack(side="right", padx=2)
        Tip(ab, "Add a line at the end of the file; its number is the id a script or table uses."
            if m.is_text else "Add a key with a value.")
        self.which = ttk.Label(head, text="Pick a line to edit it.", font=("Segoe UI", 9, "bold"))
        self.which.pack(side="left")
        self._insert_head = head
        foot = ttk.Frame(ed)
        foot.pack(side="bottom", fill="x")                # below the text box, always visible
        ap = ttk.Button(foot, text="Apply (Ctrl+Enter)", command=self.apply)
        ap.pack(side="right", padx=2)
        self.revert_btn = ttk.Button(foot, text="Revert line", command=self.revert)
        self.revert_btn.pack(side="right", padx=2)
        Tip(self.revert_btn, "Back to the text the file had when it was opened.")
        self.issues = ttk.Label(foot, text="", foreground="#b5471b", wraplength=520, justify="left")
        self.issues.pack(side="left", fill="x", expand=True)
        self.edit = tk.Text(ed, height=5, wrap="word", undo=True, font=("Segoe UI", 10))
        self.edit.pack(fill="both", expand=True, pady=(4, 2))
        self.edit.bind("<Control-Return>", lambda _e: (self.apply(), "break")[1])
        self.edit.bind("<<Modified>>", self._on_typed)
        im = insert_menu(self._insert_head, self.edit)
        im.pack(side="right", padx=2)
        Tip(im, "Put a colour, a raise / lower, a button icon or a ＠ code at the cursor. "
                "Characters that can't be typed are written as backslash escapes (\\red, "
                "\\btn(a) ...); a real backslash is \\\\.")
        pw.add(ed, weight=1)

    # ---- list -------------------------------------------------------------------------- #
    def _shown(self, key, text):
        q = self.q.get().strip().lower()
        if q and q not in text.lower() and q not in textesc.to_edit(text).lower() and q != str(key).lower():
            return False
        mode = self.only.get()
        if mode == "changed" and not self.m.changed(key):
            return False
        if mode == "with problems" and not problems(text):
            return False
        return True

    def refill(self):
        tv, m = self.tv, self.m
        tv.delete(*tv.get_children())
        n = 0
        for key, text in m.rows.items():
            if not self._shown(key, text):
                continue
            tv.insert("", "end", iid=self._iid(key), values=(key, shown(text)),
                      tags=self._tags(key, text))
            n += 1
            if n >= MAX_ROWS:
                tv.insert("", "end", iid="…", values=("…", "(showing the first %d; search to narrow)" % MAX_ROWS))
                break
        nch = sum(1 for k in m.rows if m.changed(k))
        self.count.config(text="%s %s%s" % (format(len(m.rows), ","), "lines" if m.is_text else "keys",
                                            ("  ·  %d changed" % nch) if nch else ""))
        if self.sel is not None and tv.exists(self._iid(self.sel)):
            tv.selection_set(self._iid(self.sel))
            tv.see(self._iid(self.sel))

    def _iid(self, key):
        return "k:%s" % key

    def _key(self, iid):
        k = iid[2:]
        return int(k) if self.m.is_text else k

    def _tags(self, key, text):
        t = []
        if self.m.changed(key):
            t.append("changed")
        if problems(text):
            t.append("problem")
        return t

    def _on_select(self, _e=None):
        s = self.tv.selection()
        if not s or not s[0].startswith("k:"):
            return
        self.show(self._key(s[0]))

    def show(self, key):
        self.sel = key
        text = self.m.rows[key]
        self.which.config(text=("Line %d" % key) if self.m.is_text else ("Key “%s”" % key))
        self.edit.delete("1.0", "end")
        self.edit.insert("1.0", textesc.to_edit(text))
        self.edit.edit_modified(False)
        self.edit.edit_reset()
        self._show_issues(textesc.to_edit(text))

    def _on_typed(self, _e=None):
        if self.edit.edit_modified():
            self._show_issues(self.typed())
            self.edit.edit_modified(False)

    def typed(self):
        """What is in the box (the notation)."""
        return self.edit.get("1.0", "end-1c")

    def _show_issues(self, notation):
        bad = textesc.check(notation)
        if bad is not None:
            self.issues.config(text="• error: %s" % bad, foreground="#c01c28")
            return
        iss = problems(textesc.from_edit(notation))
        self.issues.config(text=textlint.format_issues(iss, 3) if iss else "",
                           foreground="#c01c28" if any(x.level == "error" for x in iss) else "#b5471b")

    # ---- edits ------------------------------------------------------------------------- #
    def apply(self, text=None, quiet=False):
        """Put the typed text (or `text`) into the selected line. Refused when the game could
        crash on it. True when applied."""
        if self.sel is None:
            return False
        if text is None:                               # the box holds the notation
            try:
                text = textesc.from_edit(self.typed())
            except textesc.EscapeError as e:
                if not quiet:
                    messagebox.showerror("Not applied", str(e))
                return False
        errs = [x for x in textlint.lint(text) if x.level == "error"]
        if errs:
            if not quiet:
                messagebox.showerror("Not applied", "The game could crash on this line:\n\n"
                                     + textlint.format_issues(errs))
            return False
        if text == self.m.rows[self.sel]:
            return True
        self.m.set(self.sel, text)
        self._changed("Changed %s" % self._what(self.sel))
        return True

    def revert(self):
        if self.sel is None or self.sel not in self.m.original:
            return
        self.m.set(self.sel, self.m.original[self.sel])
        self.show(self.sel)
        self._changed("Reverted %s" % self._what(self.sel))

    def new_row(self, key=None, text=""):
        if self.m.is_text:
            key = self.m.add(value=text)
        else:
            if key is None:
                key = _ask(self.doc.content, "New key", "Name of the new key:")
                if not key:
                    return None
            try:
                key = self.m.add(key, text)
            except ValueError as e:
                messagebox.showerror("New key", str(e))
                return None
        self.sel = key
        self.q.set("")
        self._changed("Added %s" % self._what(key))
        self.show(key)
        self.edit.focus_set()
        return key

    def delete_key(self, key=None):
        key = self.sel if key is None else key
        if key is None or self.m.is_text:
            return
        self.m.remove(key)
        self.sel = None
        self.edit.delete("1.0", "end")
        self.which.config(text="Pick a line to edit it.")
        self._changed("Deleted key “%s”" % key)

    def _what(self, key):
        return ("line %d" % key) if self.m.is_text else ("key “%s”" % key)

    def _changed(self, msg):
        self.doc.cur_data = self.m.build()
        self.doc._export_arc = self.m.arc if self.m.is_text else None
        self.refill()
        self._status(msg + " -- Save writes the file")

    def _status(self, text):
        try:
            self.app.status.config(text=text)
        except Exception:
            pass

    # ---- saving ------------------------------------------------------------------------- #
    def target(self):
        """(path, 'file' | 'game') where Save writes, or (None, None) without a game folder."""
        key = self.doc.key
        if key and key[0] == "file":
            return pathlib.Path(key[1]), "file"
        fn = pathlib.Path(self.name).name
        t = gamepaths.game_targets([fn])
        if t is None:
            return None, None
        return t[fn], "game"

    def save(self):
        path, kind = self.target()
        if path is None:
            return self.save_as()
        blob = self.m.build()
        try:
            if kind == "game":
                backup = gamepaths.write_game_file(path, blob)
            else:
                path.write_bytes(blob)
                backup = None
        except OSError as e:
            messagebox.showerror("Save", "Could not write %s:\n%s\n\n(Is the game running with it open?)"
                                 % (path, e))
            return None
        self._saved(blob)
        note = self._reload_note()
        self._status("Saved %s%s -- %s" % (path, " (original kept in %s)" % gamepaths.BACKUP_DIR
                                           if backup else "", note))
        return path

    def save_as(self, path=None):
        if path is None:
            path = filedialog.asksaveasfilename(title="Save the text file as",
                                                initialfile=pathlib.Path(self.name).name)
            if not path:
                return None
        blob = self.m.build()
        pathlib.Path(path).write_bytes(blob)
        self._saved(blob)
        self._status("Saved %s" % path)
        return pathlib.Path(path)

    def _saved(self, blob):
        self.doc.cur_data = blob
        self.app._mark_saved(self.doc)
        self.m.original = dict(self.m.rows)
        self.refill()

    def _reload_note(self):
        n = pathlib.Path(self.name).name.lower()
        if n.startswith("rf3mc."):
            return "the game keeps dialogue in memory: ⟳ Reload in game (Cutscene Editor) or restart"
        return "restart the game to see it (the editors' names follow at once)"


def _ask(parent, title, prompt):
    """A one-line text question; None when cancelled."""
    top = tk.Toplevel(parent)
    top.title(title)
    top.transient(parent.winfo_toplevel())
    ttk.Label(top, text=prompt).pack(padx=12, pady=(10, 4), anchor="w")
    v = tk.StringVar()
    e = ttk.Entry(top, textvariable=v, width=40)
    e.pack(padx=12, fill="x")
    out = {}

    def ok(_e=None):
        out["v"] = v.get().strip()
        top.destroy()
    row = ttk.Frame(top)
    row.pack(pady=10)
    ttk.Button(row, text="OK", command=ok).pack(side="left", padx=4)
    ttk.Button(row, text="Cancel", command=top.destroy).pack(side="left", padx=4)
    e.bind("<Return>", ok)
    top.bind("<Escape>", lambda _e: top.destroy())
    e.focus_set()
    top.grab_set()
    top.wait_window()
    return out.get("v") or None
