"""Small Tk helpers shared by the toolkit's GUIs (rf4mod_gui, map_editor, cutscene_editor):
the no-live-resize PanedWindow, hover tips, filterable comboboxes, commit-on-leave
entries, a scrollable column, and destroy-safe after() scheduling."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class Paned(tk.PanedWindow):
    """Drop-in for ttk.PanedWindow that does NOT re-lay-out its panes on every pixel of a
    sash drag.

    On Windows every Tk widget is a native window, so moving a sash moves and repaints the
    whole pane on the far side: with the map editor open that was 2-4 s PER STEP of a drag
    (measured 2026-09-24), i.e. the window froze while resizing the files pane. With
    opaqueresize off, a drag shows only the sash line and the panes are laid out once, on
    release.

    Accepts the ttk calling convention used in the toolkit: add(child, weight=N) and
    insert(pos, child, weight=N). weight 0 = the pane keeps its width when the window
    grows (stretch="never"); any other weight shares the extra space (stretch="always")."""

    def __init__(self, parent, orient="horizontal", **kw):
        opts = dict(orient=orient, opaqueresize=False, sashwidth=6, sashrelief="flat",
                    borderwidth=0, showhandle=False)
        try:
            bg = ttk.Style(parent).lookup("TFrame", "background")
            if bg:
                opts["background"] = bg
        except tk.TclError:
            pass
        opts.update(kw)
        super().__init__(parent, **opts)

    @staticmethod
    def _pane_opts(weight, kw):
        if weight is not None and "stretch" not in kw:
            kw["stretch"] = "always" if weight else "never"
        return kw

    def add(self, child, weight=None, **kw):
        super().add(child, **self._pane_opts(weight, kw))

    def insert(self, pos, child, weight=None, **kw):
        """ttk-style insert: put `child` at index `pos`."""
        panes = [str(p) for p in self.panes()]
        kw = self._pane_opts(weight, kw)
        if 0 <= pos < len(panes):
            kw["before"] = panes[pos]
        super().add(child, **kw)

    def sashpos(self, index, newpos=None):
        """ttk-style sash position get/set (x for horizontal, y for vertical panes)."""
        horiz = str(self.cget("orient")) == "horizontal"
        if newpos is None:
            x, y = self.sash_coord(index)
            return x if horiz else y
        x, y = self.sash_coord(index)
        if horiz:
            self.sash_place(index, newpos, y)
        else:
            self.sash_place(index, x, newpos)
        return newpos

HINT_FONT = ("Segoe UI", 8)
SMALL_FONT = ("Segoe UI", 7)
MONO = ("Consolas", 9)
GOOD = "#2a8"
MUTED = "#888"


def later(widget, fn, ms=0):
    """widget.after / after_idle that is cancelled when `widget` is destroyed, so a
    callback never fires into a torn-down editor (Tk reports those as 'invalid command
    name'). Returns the after id."""
    ids = widget.__dict__.setdefault("_later_ids", set())
    if not widget.__dict__.get("_later_bound"):
        def cancel_all(e, w=widget):
            if e.widget is w:
                for i in list(w.__dict__.get("_later_ids", ())):
                    try:
                        w.after_cancel(i)
                    except Exception:
                        pass
        widget.bind("<Destroy>", cancel_all, add="+")
        widget._later_bound = True
    handle = []

    def run():
        ids.discard(handle[0])
        fn()
    handle.append(widget.after(ms, run) if ms else widget.after_idle(run))
    ids.add(handle[0])
    return handle[0]


def shortcut_scope(frame, tag, bindings, home=None):
    """Editor-wide Ctrl shortcuts that work wherever the keyboard focus is inside `frame`,
    including widgets built later (panels that rebuild their forms on every selection).

    `bindings` = [(letter, fn(event))]; each letter is bound in both cases, so Caps Lock
    doesn't turn Ctrl+S into an unbound <Control-S>. The handler gets the event: tell undo
    from redo by the Shift bit (event.state & 1), not by the letter's case. Every widget
    under `frame` gets `tag` now, and any widget created later gets it the moment it takes
    the focus (before a key can reach it).

    When the focused widget is destroyed (a panel rebuilding its form right after an edit
    applied), Tk drops the focus onto the bare toplevel, outside the scope, and the next
    Ctrl+S would go nowhere until the user clicked somewhere. The focus is handed to
    `home()` (a widget inside `frame`; default the frame itself) instead.

    Returns a retag(widget=None) function for callers that want to tag a subtree now."""
    for letter, fn in bindings:
        for seq in ("<Control-%s>" % letter.lower(), "<Control-%s>" % letter.upper()):
            frame.bind_class(tag, seq, lambda e, fn=fn: (fn(e), "break")[1])
    top = frame.winfo_toplevel()
    focused = {"w": None}

    def refocus():
        try:
            f = frame.focus_get()
        except (KeyError, tk.TclError):            # focus on a widget being torn down
            f = None
        if f is None or f is top:
            target = (home() if home else None) or frame
            try:
                if target.winfo_exists():
                    target.focus_set()
            except tk.TclError:
                pass

    def on_destroy(e):
        if e.widget is focused["w"]:
            focused["w"] = None
            frame.after_idle(refocus)
    frame.bind_class(tag, "<Destroy>", on_destroy, add="+")

    def retag(w=None):
        stack = [frame if w is None else w]
        while stack:
            x = stack.pop()
            tags = x.bindtags()
            if tag not in tags:
                x.bindtags((tags[0], tag) + tags[1:])
            stack.extend(x.winfo_children())

    inside = str(frame) + "."

    def on_focus(e):
        w = e.widget
        if isinstance(w, tk.Misc) and (w is frame or str(w).startswith(inside)):
            tags = w.bindtags()
            if tag not in tags:
                w.bindtags((tags[0], tag) + tags[1:])
            focused["w"] = w
    top.bind("<FocusIn>", on_focus, add="+")
    retag()
    return retag


def hint(parent, text, wrap=320, **kw):
    lab = ttk.Label(parent, text=text, font=SMALL_FONT, foreground=MUTED, wraplength=wrap,
                    justify="left", **kw)
    return lab


def section(parent, title):
    f = ttk.LabelFrame(parent, text=title, padding=(6, 3))
    f.pack(fill="x", padx=4, pady=(4, 2))
    return f


def commit_entry(parent, var, on_commit, width=8, **kw):
    """An Entry that calls on_commit() on Enter and on focus loss. The editor calls
    `entry._commit()` itself before anything that changes what the form shows (clicking
    the canvas, undo, switching tool), so a typed value always lands on the object it was
    typed for."""
    e = ttk.Entry(parent, textvariable=var, width=width, **kw)

    def fire(_e=None):
        on_commit()
    e._commit = fire
    e.bind("<Return>", fire)
    e.bind("<KP_Enter>", fire)
    e.bind("<FocusOut>", fire)
    return e


class FilterCombo(ttk.Combobox):
    """A combobox whose list narrows to the entries containing what was typed (any word,
    case-insensitive). Picking an entry or pressing Enter calls on_pick(text)."""

    def __init__(self, parent, values, on_pick=None, width=30, **kw):
        self._all = list(values)
        self._var = kw.pop("textvariable", None) or tk.StringVar()
        super().__init__(parent, textvariable=self._var, values=self._all, width=width,
                         height=20, **kw)
        self._on_pick = on_pick
        self.bind("<KeyRelease>", self._filter)
        self.bind("<<ComboboxSelected>>", self._picked)
        self.bind("<Return>", self._picked)
        self.bind("<FocusOut>", self._restore)
        self._commit = lambda: None       # picks commit immediately; nothing pending

    @property
    def var(self):
        return self._var

    def set_values(self, values):
        self._all = list(values)
        self.configure(values=self._all)

    def _filter(self, e):
        if e.keysym in ("Return", "KP_Enter", "Up", "Down", "Escape", "Tab"):
            return
        words = self._var.get().lower().split()
        vals = [v for v in self._all if all(w in v.lower() for w in words)] if words else self._all
        self.configure(values=vals[:400])

    def _picked(self, _e=None):
        self.configure(values=self._all)
        if self._on_pick:
            self._on_pick(self._var.get())

    def _restore(self, _e=None):
        self.configure(values=self._all)


def ask_yes_no_optout(parent, title, message, yes="Yes", no="Cancel",
                      optout="Don't ask again this session"):
    """A modal yes / no question with an opt-out checkbox (a messagebox has no room for
    one). Returns (answer, opted_out): Enter = yes, Esc or closing the window = no; the
    checkbox counts whichever button was pressed."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.resizable(False, False)
    win.transient(parent)
    f = ttk.Frame(win, padding=14)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text=message, wraplength=420, justify="left").pack(anchor="w")
    skip = tk.BooleanVar(value=False)
    ttk.Checkbutton(f, text=optout, variable=skip).pack(anchor="w", pady=(12, 0))
    res = {"ok": False}

    def done(ok):
        res["ok"] = ok
        win.destroy()
    b = ttk.Frame(f)
    b.pack(fill="x", pady=(12, 0))
    ttk.Button(b, text=no, command=lambda: done(False)).pack(side="right")
    yb = ttk.Button(b, text=yes, command=lambda: done(True))
    yb.pack(side="right", padx=(0, 6))
    win.bind("<Return>", lambda _e: done(True))
    win.bind("<Escape>", lambda _e: done(False))
    win.protocol("WM_DELETE_WINDOW", lambda: done(False))
    win.update_idletasks()
    try:                                        # centred on the parent window
        x = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    except tk.TclError:
        pass
    yb.focus_set()
    win.grab_set()
    parent.wait_window(win)
    return res["ok"], bool(skip.get())


class Tip:
    """Hover help for a widget (shown after a short delay)."""

    def __init__(self, widget, text, delay=500):
        self.w, self.text, self.delay = widget, text, delay
        self._after = self._top = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._hide()
        self._after = later(self.w, self._show, self.delay)

    def _show(self):
        text = self.text() if callable(self.text) else self.text
        if not text:
            return
        self._top = tk.Toplevel(self.w)
        self._top.wm_overrideredirect(True)
        x = self.w.winfo_rootx() + 8
        y = self.w.winfo_rooty() + self.w.winfo_height() + 4
        self._top.wm_geometry(f"+{x}+{y}")
        tk.Label(self._top, text=text, justify="left", bg="#222", fg="#eee", font=("Consolas", 8),
                 bd=1, relief="solid", padx=4, pady=2, wraplength=520).pack()

    def _hide(self, _e=None):
        if self._after:
            self.w.after_cancel(self._after)
            self._after = None
        if self._top is not None:
            self._top.destroy()
            self._top = None


class ScrollFrame(ttk.Frame):
    """A vertically scrollable column. `.body` is the frame to fill. Wheel notches that
    arrive in a burst are summed into one scroll: every step moves all the column's native
    child windows, which is the expensive part on Windows."""

    def __init__(self, parent, width=330):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, width=width)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=(0, 0, e.width, e.height)))
        self._seen_w = None
        self.canvas.bind("<Configure>", self._width)
        self._n = 0
        self._pending = False
        self.bind_wheel(self.canvas)

    def _width(self, e):
        if e.width != self._seen_w:
            self._seen_w = e.width
            self.canvas.itemconfigure(self._win, width=e.width)

    def bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self._wheel, add="+")

    def bind_wheel_tree(self, widget=None):
        """Route wheel events from every descendant (except list-like widgets that scroll
        themselves) to this column."""
        w = widget or self.body
        if not isinstance(w, (tk.Listbox, tk.Text, ttk.Treeview, ttk.Combobox)):
            self.bind_wheel(w)
        for c in w.winfo_children():
            self.bind_wheel_tree(c)

    def _wheel(self, e):
        self._n += -(e.delta // 120) * 2
        if not self._pending:
            self._pending = True
            later(self, self._flush, 15)

    def _flush(self):
        n, self._n, self._pending = self._n, 0, False
        if n and self.body.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(n, "units")

    def to_top(self):
        self.canvas.yview_moveto(0)


def set_text(widget, text):
    """Replace the contents of a (possibly disabled) Text widget."""
    st = widget.cget("state")
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", text)
    widget.configure(state=st)


def to_int(text, default=None):
    try:
        return int(str(text).strip(), 0)
    except (TypeError, ValueError):
        return default
