"""The Script tab: the open scene as selectable rows, in the readable story form or the
technical listing, with keyboard navigation and Alt-hover explanations."""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import guiutil

from rf4s_modkit import script

from .render import Row, SceneText

BG, FG = "#15151b", "#dcdce4"
TAGS = {"addr": "#5c5c6a", "opc": "#7f8fa6", "hdr": "#ffd479", "hdrv": "#c9b27a", "lbl": "#ffb454",
        "dlg": "#e8e8ef", "act": "#8fb7d9", "flow": "#f0a868", "cond": "#e08fd0",
        "dim": "#7c7c8a", "emf": "#7fd6a0", "warn": "#e06060", "narr": "#b0b0bc"}


class ScriptView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.mode = "story"
        self.show_addr = False
        self.show_ops = False
        self.show_file_off = False          # each statement's offset in rf3.mc, both views
        sb = ttk.Scrollbar(self)
        sb.pack(side="right", fill="y")
        self.text = tk.Text(self, wrap="word", font=("Segoe UI", 10), bg=BG, fg=FG,
                            insertbackground=FG, state="disabled", cursor="arrow",
                            yscrollcommand=sb.set, padx=8, pady=6, spacing1=1, spacing3=1,
                            takefocus=True, highlightthickness=0)
        self.text.pack(side="left", fill="both", expand=True)
        sb.config(command=self.text.yview)
        for tag, col in TAGS.items():
            self.text.tag_configure(tag, foreground=col)
        self.text.tag_configure("hdr", font=("Segoe UI", 9, "bold"))
        self.text.tag_configure("lbl", font=("Consolas", 10, "bold"), spacing1=6)
        self.text.tag_configure("code", font=("Consolas", 10))
        self.text.tag_configure("selrow", background="#23405a")
        self.text.tag_configure("focusrow", background="#5a4a00")
        self.text.tag_configure("bprow", background="#4a1616")     # a breakpoint
        self.text.tag_configure("bpwait", background="#3a2e2e")    # one that cannot fire yet
        self.text.tag_configure("pcrow", background="#1e5a2a")     # where a script stopped
        self.text.tag_raise("sel")
        self.rows = []                 # display line (1-based) -> Row, as a list index line-1
        self._key_line = {}            # (pc, option) -> line
        self.sel = None                # (pc, option)
        self._spk_tags = set()
        self._tip = None
        self._hover_row = None
        t = self.text
        t.bind("<Button-1>", self._click)
        t.bind("<Double-Button-1>", lambda e: (self._click(e), app.focus_editor(), "break")[2])
        # rows are selected whole: Tk's own drag / shift / triple-click text selection would
        # extend from a stale anchor (the click handler never moves it) to the bottom
        for seq in ("<B1-Motion>", "<B1-Leave>", "<Shift-Button-1>", "<Triple-Button-1>",
                    "<Control-a>", "<Control-slash>"):
            t.bind(seq, lambda _e: "break")
        t.bind("<Control-c>", lambda _e: (self.copy_row(), "break")[1])
        t.bind("<Up>", lambda _e: self.move(-1))
        t.bind("<Down>", lambda _e: self.move(1))
        t.bind("<Prior>", lambda _e: self.move(-15))
        t.bind("<Next>", lambda _e: self.move(15))
        t.bind("<Home>", lambda _e: self.move(-10 ** 6))
        t.bind("<End>", lambda _e: self.move(10 ** 6))
        t.bind("<Return>", lambda _e: (app.focus_editor(), "break")[1])
        t.bind("<Delete>", lambda _e: (app.delete_selected(), "break")[1])
        t.bind("<Insert>", lambda _e: (app.ask_insert_instruction(), "break")[1])
        t.bind("<F9>", lambda _e: (app.toggle_breakpoint(), "break")[1])
        t.bind("<Button-3>", self._context_menu)
        t.bind("<Motion>", self._motion)
        t.bind("<Leave>", lambda _e: self.hide_tip())
        # Alt shows the explanation (it used to be Ctrl, which Ctrl+S / Ctrl+Z share). The
        # "break" keeps a bare Alt from reaching Tk's tk::WinMenuKey, which on Windows would
        # put the window into menu mode and eat the next key.
        top = self.winfo_toplevel()
        for seq in ("<KeyPress-Alt_L>", "<KeyPress-Alt_R>"):
            top.bind(seq, lambda _e: (self._alt(True), "break")[1], add="+")
        for seq in ("<KeyRelease-Alt_L>", "<KeyRelease-Alt_R>"):
            top.bind(seq, lambda _e: (self._alt(False), "break")[1], add="+")

    # ---- rendering -------------------------------------------------------- #
    def render(self, keep_sel=True):
        app = self.app
        sc, bank = app.scene, app.bank
        t = self.text
        y = t.yview()[0]
        t.config(state="normal")
        t.delete("1.0", "end")
        self.rows = []
        self._key_line = {}
        if sc is None:
            t.insert("end", "Pick a scene in the browser on the left, or search for what a "
                            "character says.", "dim")
            t.config(state="disabled")
            return
        st_text = SceneText(app.doc, bank, sc)
        rows = (st_text.story_rows(self.show_addr, self.show_ops, self.show_file_off) if self.mode == "story"
                else self._code_rows(st_text))
        for n, row in enumerate(rows, 1):
            for s, tag in row.segs:
                if isinstance(tag, tuple):                # ("spk" | "cue", colour)
                    tag = self._spk_tag(tag[1], bold=(tag[0] == "spk"))
                t.insert("end", s, (tag, "code") if (self.mode == "code" and tag) else tag or ())
            t.insert("end", "\n")
            self.rows.append(row)
            if row.key is not None and row.key not in self._key_line:
                self._key_line[row.key] = n
        t.config(state="disabled")
        self.mark_debug()
        if keep_sel and self.sel in self._key_line:
            self._highlight(self.sel, see=False)
            t.yview_moveto(y)
        else:
            self.sel = None

    def mark_debug(self):
        """Tint the rows of statements with a breakpoint, and the row a script stopped at."""
        app, t = self.app, self.text
        t.tag_remove("bprow", "1.0", "end")
        t.tag_remove("bpwait", "1.0", "end")
        t.tag_remove("pcrow", "1.0", "end")
        bank = app.bank_pos
        bps = {pc for b, pc in getattr(app, "breakpoints", ()) if b == bank}
        waits = {pc for b, pc in getattr(app, "pending_breakpoints", ()) if b == bank}
        cur = getattr(app, "debug_current", None)
        for key, ln in self._key_line.items():
            if key[1] is not None:
                continue
            if key[0] in bps:
                t.tag_add("bpwait" if key[0] in waits else "bprow", "%d.0" % ln, "%d.0" % (ln + 1))
            if cur is not None and cur == (bank, key[0]):
                t.tag_add("pcrow", "%d.0" % ln, "%d.0" % (ln + 1))
                t.see("%d.0" % ln)
        t.tag_raise("pcrow")

    def _code_rows(self, st_text):
        sc = st_text.scene
        rows = []
        lin = script.linearize(sc)
        shown = {pc for pc, _ in lin}
        rest = [(pc, st) for pc, st in sc.stmts.items() if pc not in shown]
        for part, seq in (("main", lin), ("rest", rest)):
            if part == "rest" and seq:
                rows.append(Row([("; --- other branches / paths ---", "hdr")]))
            for pc, st in seq:
                lbl = st_text.labels.get(pc, "")
                ops = [(st_text.raw_op(st), "opc")] if self.show_ops else []
                foff = [st_text.file_offset_seg(pc)] if self.show_file_off else []
                rows.append(Row(foff + [("%-7s" % (lbl + ":" if lbl else ""), "lbl")] + ops +
                                [(st_text.code_line(st), "dlg" if st.mnem == "DIALOG" else "act")],
                                (pc, None), st))
        return rows

    def _spk_tag(self, color, bold=True):
        """A speaker's colour: bold on the dialogue line, plain and small on the cue row."""
        tag = ("spk" if bold else "cue") + color.lstrip("#")
        if tag not in self._spk_tags:
            self.text.tag_configure(tag, foreground=color,
                                    font=("Segoe UI", 10, "bold") if bold else ("Segoe UI", 8))
            self._spk_tags.add(tag)
        return tag

    # ---- selection ---------------------------------------------------------- #
    def _line_at(self, e):
        return int(self.text.index("@%d,%d" % (e.x, e.y)).split(".")[0])

    def _context_menu(self, e):
        """Right-click: select the row, then offer the insert / delete actions."""
        self._click(e)
        app = self.app
        m = tk.Menu(self.text, tearoff=False)
        has = app.sel is not None
        st = "normal" if has else "disabled"
        # one entry: the instruction window has its own "after / before it" choice
        m.add_command(label="Add instruction…  (Insert)", state=st,
                      command=lambda: app.ask_insert_instruction())
        m.add_separator()
        m.add_command(label="Copy line  (Ctrl+C)", state=st, command=self.copy_row)
        m.add_command(label="Delete  (Del)", state=st, command=app.delete_selected)
        m.add_separator()
        m.add_command(label="Toggle breakpoint  (F9)", state=st, command=app.toggle_breakpoint)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()
        return "break"

    def _click(self, e):
        self.text.focus_set()
        self.text.tag_remove("sel", "1.0", "end")
        ln = self._line_at(e)
        row = self.rows[ln - 1] if 0 < ln <= len(self.rows) else None
        if row is None or row.key is None:
            return "break"
        self.app.select(row.key)
        return "break"

    def _highlight(self, key, see=True):
        t = self.text
        t.tag_remove("selrow", "1.0", "end")
        ln = self._key_line.get(key)
        if ln is None:
            return
        t.tag_add("selrow", f"{ln}.0", f"{ln + 1}.0")
        if see:
            t.see(f"{ln}.0")

    def set_selection(self, key, see=True):
        self.sel = key
        self._highlight(key, see)

    def move(self, delta):
        keys = [r.key for r in self.rows if r.key is not None]
        if not keys:
            return "break"
        if self.sel in keys:
            i = keys.index(self.sel)
            j = max(0, min(len(keys) - 1, i + (1 if delta > 0 else -1) * max(1, abs(delta))))
        else:
            j = 0 if delta > 0 else len(keys) - 1
        self.app.select(keys[j])
        return "break"

    def focus_pc(self, pc):
        """Scroll to a statement and mark it (a jump from the map editor / Callers)."""
        key = (pc, None)
        ln = self._key_line.get(key)
        t = self.text
        t.tag_remove("focusrow", "1.0", "end")
        if ln is None:
            return False
        t.tag_add("focusrow", f"{ln}.0", f"{ln + 1}.0")
        self.app.select(key)
        return True

    def line_of(self, key):
        return self._key_line.get(key)

    def copy_row(self):
        """Ctrl+C: the selected row's text to the clipboard."""
        ln = self._key_line.get(self.sel)
        if ln is None:
            return
        s = self.text.get(f"{ln}.0", f"{ln}.end").strip()
        self.text.clipboard_clear()
        self.text.clipboard_append(s)
        self.app.status("copied: " + (s if len(s) < 80 else s[:77] + "…"))

    # ---- Alt-hover explanation ----------------------------------------------------- #
    # Tk's Alt bit: 0x20000 on Windows (Mod1 = 0x0008 is Num Lock there), Mod1 elsewhere
    ALT_MASK = 0x20000 if sys.platform == "win32" else 0x0008

    def _motion(self, e):
        ln = self._line_at(e)
        row = self.rows[ln - 1] if 0 < ln <= len(self.rows) else None
        self._hover_row = (row, e.x_root + 16, e.y_root + 18) if (row and row.st is not None) else None
        if e.state & self.ALT_MASK and self._hover_row:
            self._show_hover()
        else:
            self.hide_tip()

    def _alt(self, down):
        if down and self._hover_row:
            self._show_hover()
        elif not down:
            self.hide_tip()

    def _show_hover(self):
        row, x, y = self._hover_row
        text = SceneText(self.app.doc, self.app.bank, self.app.scene).explain(row.st)
        if self._tip is None:
            self._tip = tk.Toplevel(self)
            self._tip.wm_overrideredirect(True)
            if sys.platform == "win32":
                try:                        # a popup that can't be activated can't take focus
                    self._tip.wm_attributes("-disabled", True)
                except tk.TclError:
                    pass
            lbl = tk.Label(self._tip, justify="left", anchor="w", bg="#1b1b22", fg="#e6e6ee",
                           font=("Segoe UI", 9), relief="solid", bd=1, padx=8, pady=6)
            lbl.config(wraplength=min(tkfont.Font(font=lbl["font"]).measure("m" * 60),
                                           guiutil.tip_wraplength(lbl, x, y, 10 ** 6)))
            lbl.pack()
            self._tip_lbl = lbl
        if self._tip_lbl.cget("text") != text:
            self._tip_lbl.config(text=text)
        guiutil.place_popup(self._tip, x, y)   # kept on the monitor
        had = self.focus_get()
        self._tip.deiconify()
        if had is not None and self.focus_get() is not had:
            had.focus_set()                 # showing it must never move the keyboard focus

    def hide_tip(self):
        if self._tip is not None:
            self._tip.withdraw()
