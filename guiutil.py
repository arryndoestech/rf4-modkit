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
