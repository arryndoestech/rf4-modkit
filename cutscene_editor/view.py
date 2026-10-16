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
        "dim": "#7c7c8a", "emf": "#7fd6a0", "warn": "#e06060", "narr": "#b0b0bc",
        # View -> Operands: one colour per operand, cycling (render.SceneText.operand_segs)
        "opd0": "#ff9e64", "opd1": "#7dcfff", "opd2": "#c3e88d", "opd3": "#f7768e",
        "opd4": "#bb9af7", "opd5": "#e0c070"}



def _ypixels(t, a, b):
    """Display pixels from index a down to index b (0 when b is on a's first display line)."""
    n = t.count(a, b, "ypixels")
    if isinstance(n, tuple):
        n = n[0]
    return int(n or 0)

class _JumpLinks:
    """Finds the jump targets in a row's text: the scene's labels (L1, L2 ...) and, for a
    statement's own targets outside the scene, their 0x1234 address. Dialogue, the label
    column, addresses and opcodes are never links."""

    PLAIN = ("dlg", "lbl", "addr", "opc", "hdr", "hdrv", "xreflink")

    def __init__(self, st_text):
        import re
        self.by_name = {name: pc for pc, name in st_text.labels.items()}
        names = sorted(self.by_name, key=len, reverse=True)
        self.re = re.compile(r"(?<![\w:])(%s|0x[0-9a-fA-F]{4})(?!\w)" % "|".join(map(re.escape, names))
                             if names else r"(?<![\w:])(0x[0-9a-fA-F]{4})(?!\w)")

    def split(self, text, tag, st):
        """[(piece, target pc or None)] covering `text`."""
        if tag in self.PLAIN or not text:
            return [(text, None)]
        targets = set(t for t in (getattr(st, "code_targets", None) or ()) if t is not None)
        quoted = []                               # a choice's option texts: "...", never links
        q = text.find('"')
        while q >= 0:
            e = text.find('"', q + 1)
            if e < 0:
                break
            quoted.append((q, e))
            q = text.find('"', e + 1)
        out, at = [], 0
        for m in self.re.finditer(text):
            if any(a <= m.start() <= b for a, b in quoted):
                continue
            tok = m.group(1)
            if tok.lower().startswith("0x"):
                pc = int(tok, 16)
                if pc not in targets:             # an operand or an address, not a jump
                    continue
            else:
                pc = self.by_name[tok]
            if m.start() > at:
                out.append((text[at:m.start()], None))
            out.append((tok, pc))
            at = m.end()
        if at < len(text):
            out.append((text[at:], None))
        return out or [(text, None)]


class ScriptView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.mode = "story"
        self.show_addr = False
        self.show_ops = False
        self.show_file_off = False          # each statement's offset in rf3.mc, both views
        self.show_operands = False          # each statement's operands in hex, one colour each
        self.show_xrefs = False             # each label: how many statements lead to it
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
        self.text.tag_configure("xreflink", foreground="#7fb4ff", underline=True)   # View → Xref counts
        self.text.tag_configure("jumplink", underline=True)       # a jump target: click goes there
        self.text.tag_raise("sel")
        self.rows = []                 # display line (1-based) -> Row, as a list index line-1
        self._key_line = {}            # (pc, option) -> line
        self.sel = None                # (pc, option): the row the Inspector shows
        self.multi = []                # a multi-row selection (display order), else []
        self._anchor = None            # where a Shift range starts
        self._spk_tags = set()
        self._tip = None
        self._hover_row = None
        t = self.text
        t.bind("<Button-1>", self._click)
        t.bind("<Double-Button-1>", self._double_click)
        # rows are selected whole: Tk's own drag / shift / triple-click text selection would
        # extend from a stale anchor (the click handler never moves it) to the bottom
        for seq in ("<B1-Motion>", "<B1-Leave>", "<Triple-Button-1>", "<Control-slash>"):
            t.bind(seq, lambda _e: "break")
        # several rows: Ctrl+A all, Shift+click / Shift+arrows a range, Ctrl+click one more
        for seq in ("<Control-a>", "<Control-A>"):
            t.bind(seq, lambda _e: (self.select_all(), "break")[1])
        t.bind("<Shift-Button-1>", self._shift_click)
        t.bind("<Control-Button-1>", self._ctrl_click)
        t.bind("<Shift-Up>", lambda _e: self.extend(-1))
        t.bind("<Shift-Down>", lambda _e: self.extend(1))
        t.bind("<Control-c>", lambda _e: (app.copy_selection(), "break")[1])
        t.bind("<Control-x>", lambda _e: (app.cut_selection(), "break")[1])
        t.bind("<Control-v>", lambda _e: (app.paste(), "break")[1])
        t.bind("<Up>", lambda _e: self.move(-1))
        t.bind("<Down>", lambda _e: self.move(1))
        t.bind("<Prior>", lambda _e: self.move(-15))
        t.bind("<Next>", lambda _e: self.move(15))
        t.bind("<Home>", lambda _e: self.move(-10 ** 6))
        t.bind("<End>", lambda _e: self.move(10 ** 6))
        t.bind("<Return>", lambda _e: (app.focus_editor(), "break")[1])
        t.bind("<Delete>", lambda _e: (app.delete_selected(), "break")[1])
        t.bind("<Insert>", lambda _e: (app.ask_insert_instruction(), "break")[1])
        t.bind("<F2>", lambda _e: (app.ask_edit_instruction(), "break")[1])
        t.bind("<F9>", lambda _e: (app.toggle_breakpoint(), "break")[1])
        for seq in ("<x>", "<X>"):                    # who leads here (IDA's key for it)
            t.bind(seq, lambda _e: (app.show_callers(), "break")[1])
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
        pos = self._scroll_pos() if keep_sel else None
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
        rows = (st_text.story_rows(self.show_addr, self.show_ops, self.show_file_off, self.show_operands,
                                   self.show_xrefs) if self.mode == "story"
                else self._code_rows(st_text))
        links = _JumpLinks(st_text)
        for n, row in enumerate(rows, 1):
            for s, tag in row.segs:
                if isinstance(tag, tuple):                # ("spk" | "cue", colour)
                    tag = self._spk_tag(tag[1], bold=(tag[0] == "spk"))
                    parts = [(s, None)]
                else:
                    parts = links.split(s, tag, row.st)
                for piece, pc in parts:
                    tags = (tag, "code") if (self.mode == "code" and tag) else ((tag,) if tag else ())
                    if pc is not None:
                        tags += ("jumplink", "jl:%x" % pc)
                    t.insert("end", piece, tags)
            t.insert("end", "\n")
            self.rows.append(row)
            if row.key is not None and row.key not in self._key_line:
                self._key_line[row.key] = n
        t.config(state="disabled")
        self.mark_debug()
        if keep_sel and self.sel in self._key_line:
            self._highlight(self.sel, see=False)
            if self.multi and all(k in self._key_line for k in self.multi):
                for k in self.multi:                  # a redraw keeps a multi-selection
                    ln = self._key_line[k]
                    t.tag_add("selrow", f"{ln}.0", f"{ln + 1}.0")
            else:
                self.multi = []
        else:
            self.sel = None
            self.multi = []
        if pos is not None:
            self._restore_scroll(pos)

    def _scroll_pos(self):
        """(top row, pixels of that row scrolled past) -- a redraw keeps the view by row, not
        by yview fraction: the fraction rests on Tk's estimated heights of rows not yet drawn,
        and other dialogue text (another language, a renamed speaker) changes them, so the
        same fraction lands a little higher or lower."""
        t = self.text
        try:
            top = t.index("@0,0")
            line = int(top.split(".")[0])
            info = t.dlineinfo(top)
            into = _ypixels(t, "%d.0" % line, top)
            return line, into, (info[1] if info else None)
        except tk.TclError:
            return None

    def _restore_scroll(self, pos):
        line, into, y0 = pos
        t = self.text
        try:
            t.yview("%d.0" % line)
            if y0 is None:
                return
            t.update_idletasks()
            info = t.dlineinfo("%d.0" % line)
            px = into + ((info[1] - y0) if info else 0)
            if px > 0:
                t.yview_scroll(px, "pixels")
        except tk.TclError:
            pass

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
            for k, (pc, st) in enumerate(seq):
                lbl = st_text.labels.get(pc, "")
                ops = [(st_text.raw_op(st), "opc")] if self.show_ops else []
                foff = [st_text.file_offset_seg(pc)] if self.show_file_off else []
                line = st_text.code_line(st)[7:]           # without its "xxxx:  " address
                addr = [("%04x:  " % pc, "addr")] if self.show_addr else []
                rows.append(Row(foff + [("%-7s" % (lbl + ":" if lbl else ""), "lbl")] + ops + addr +
                                [(line, "dlg" if st.mnem == "DIALOG" else "act")]
                                + ([("   ; ", "dim"), (st_text.xref_note(pc).replace("  · ", "", 1),
                                                         st_text.xref_tag(pc))]
                                   if (lbl and getattr(self, "show_xrefs", False)) else []),
                                (pc, None), st))
                # a path that runs on into a statement shown elsewhere: a shared RET is shown
                # (dimmed, at its own address), other shared code as '; -> L2'
                to = st_text.path_end(sc, pc, st, seq[k + 1][0] if k + 1 < len(seq) else None)
                if to is not None:
                    tst = sc.stmts.get(to)
                    end = "RET" if tst is not None and tst.mnem == "RET" else "; → %s" % st_text.target(to)
                    pad = [(" " * len(st_text.raw_op(st)), "opc")] if self.show_ops else []
                    addr = [("%04x:  " % to, "addr")] if self.show_addr else []
                    rows.append(Row([("%-7s" % "", "lbl")] + pad + addr + [(end, "dim")]))
        if self.show_operands:
            st_text.add_operands(rows, st_text.operand_segs)
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
        """Right-click: select the row (a row inside a multi-selection keeps it, so Copy and
        Delete act on all of them), then offer the insert / edit / delete actions."""
        if not (self.multi and self._row_key_at(e) in self.multi):
            self._click(e)
        else:
            self.text.focus_set()
        app = self.app
        m = tk.Menu(self.text, tearoff=False)
        has = app.sel is not None
        st = "normal" if has else "disabled"
        # one entry: the instruction window has its own "after / before it" choice
        m.add_command(label="Add instruction…  (Insert)", state=st,
                      command=lambda: app.ask_insert_instruction())
        cur = app.stmt(app.sel[0]) if has else None
        editable = cur is not None and not self.multi
        m.add_command(label="Edit instruction…  (F2)", state="normal" if editable else "disabled",
                      command=lambda: app.ask_edit_instruction())
        m.add_separator()
        n = len(self.multi)
        m.add_command(label=("Cut %d lines  (Ctrl+X)" % n) if n else "Cut line  (Ctrl+X)", state=st,
                      command=app.cut_selection)
        m.add_command(label=("Copy %d lines  (Ctrl+C)" % n) if n else "Copy line  (Ctrl+C)", state=st,
                      command=lambda: app.copy_selection())
        m.add_command(label="Paste after  (Ctrl+V)", state=st, command=app.paste)
        m.add_command(label=("Delete %d lines  (Del)" % n) if n else "Delete  (Del)", state=st,
                      command=app.delete_selected)
        m.add_command(label="Xrefs: who leads here…  (X)", command=app.show_callers)
        m.add_command(label="Copy this scene to another bank…", command=app.copy_scene_to_bank)
        m.add_separator()
        m.add_command(label="Toggle breakpoint  (F9)", state=st, command=app.toggle_breakpoint)
        vars_ = app.statement_vars(app.sel[0]) if (has and not n) else []
        if vars_:                                   # where else the statement's variables are used
            m.add_separator()
            for name in dict.fromkeys(nm for nm, _a in vars_):
                m.add_command(label="Uses of %s…" % name, command=lambda nm=name: app.show_var_uses(nm))
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
        target = self._jump_link_at(e)
        if target is not None:                    # a jump target: go there
            self._link_time = e.time
            if row is not None and row.key is not None:
                self.app.select(row.key)
            self.after_idle(lambda: self.app.follow_jump(target))
            return "break"
        if row is None or row.key is None:
            return "break"
        self.app.select(row.key)
        if self._on_xref_link(e):
            self._link_time = e.time
            self.after_idle(lambda k=row.key: self.app.follow_xrefs(k[0]))
        return "break"

    _link_time = None

    def _double_click(self, e):
        """Double-click: select and edit the row -- unless its first click followed an xref
        link (the scene under the mouse has changed since)."""
        if self._link_time is not None and 0 <= e.time - self._link_time < 1000:
            return "break"
        self._click(e)
        if self._link_time is not None and e.time == self._link_time:
            return "break"
        self.app.focus_editor()
        return "break"

    def _jump_link_at(self, e):
        """The pc of the jump target under the mouse ('→ L1', 'go to L2', '-> L3' ...), else None."""
        try:
            names = self.text.tag_names("@%d,%d" % (e.x, e.y))
        except tk.TclError:
            return None
        hit = next((n for n in names if n.startswith("jl:")), None)
        return int(hit[3:], 16) if hit else None

    def _on_xref_link(self, e):
        """Whether the mouse is on a label's '· N xrefs' link."""
        try:
            return "xreflink" in self.text.tag_names("@%d,%d" % (e.x, e.y))
        except tk.TclError:
            return False

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
        self.multi = []
        self._anchor = key
        self._highlight(key, see)

    # ---- several rows ------------------------------------------------------- #
    def _keys(self):
        return [r.key for r in self.rows if r.key is not None]

    def selected_keys(self):
        """The selected rows' keys in display order (one row when there is no multi-selection)."""
        if self.multi:
            return list(self.multi)
        return [self.sel] if self.sel is not None else []

    def select_keys(self, keys, primary, anchor=None, see=True):
        """Select several rows; `primary` is the one the Inspector shows."""
        want = set(keys)
        keys = [k for k in self._keys() if k in want]
        self.app.select(primary)                  # the Inspector + clears an old multi-selection
        self._anchor = anchor if anchor is not None else primary
        if len(keys) < 2:
            return
        self.multi = keys
        t = self.text
        t.tag_remove("selrow", "1.0", "end")
        for k in keys:
            ln = self._key_line.get(k)
            if ln is not None:
                t.tag_add("selrow", f"{ln}.0", f"{ln + 1}.0")
        ln = self._key_line.get(primary)
        if see and ln is not None:
            t.see(f"{ln}.0")
        n = sum(1 for k in keys if k[1] is None)
        self.app.status("%d rows selected (%d statement%s) -- Ctrl+C copies them, Del deletes the "
                        "statements" % (len(keys), n, "" if n == 1 else "s"))

    def select_all(self):
        keys = self._keys()
        if keys:
            self.text.focus_set()
            self.select_keys(keys, self.sel if self.sel in keys else keys[0], see=False)

    def _row_key_at(self, e):
        ln = self._line_at(e)
        row = self.rows[ln - 1] if 0 < ln <= len(self.rows) else None
        return row.key if row is not None else None

    def _range(self, a, b):
        keys = self._keys()
        if a not in keys or b not in keys:
            return [b]
        i, j = sorted((keys.index(a), keys.index(b)))
        return keys[i:j + 1]

    def _shift_click(self, e):
        self.text.focus_set()
        key = self._row_key_at(e)
        if key is None:
            return "break"
        anchor = self._anchor if self._anchor is not None else self.sel
        if anchor is None:
            self.app.select(key)
        else:
            self.select_keys(self._range(anchor, key), key, anchor=anchor, see=False)
        return "break"

    def _ctrl_click(self, e):
        self.text.focus_set()
        key = self._row_key_at(e)
        if key is None:
            return "break"
        cur = self.selected_keys()
        if key in cur:
            cur.remove(key)
            if not cur:
                return "break"
            self.select_keys(cur, cur[-1] if self.sel == key else self.sel, see=False)
        else:
            self.select_keys(cur + [key], key, anchor=key, see=False)
        return "break"

    def extend(self, delta):
        """Shift+Up / Down: grow or shrink the range from the anchor."""
        keys = self._keys()
        if not keys:
            return "break"
        anchor = self._anchor if self._anchor in keys else (self.sel if self.sel in keys else keys[0])
        cur = self.sel if self.sel in keys else anchor
        j = max(0, min(len(keys) - 1, keys.index(cur) + delta))
        self.select_keys(self._range(anchor, keys[j]), keys[j], anchor=anchor)
        return "break"

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
        """Scroll to a statement and mark it (a jump from the map editor / Xrefs)."""
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

    # ---- Alt-hover explanation ----------------------------------------------------- #
    # Tk's Alt bit: 0x20000 on Windows (Mod1 = 0x0008 is Num Lock there), Mod1 elsewhere
    ALT_MASK = 0x20000 if sys.platform == "win32" else 0x0008

    def _motion(self, e):
        cur = "hand2" if (self._on_xref_link(e) or self._jump_link_at(e) is not None) else "arrow"
        if self.text.cget("cursor") != cur:
            self.text.config(cursor=cur)
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
