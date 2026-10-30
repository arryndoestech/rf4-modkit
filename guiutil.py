"""Small Tk helpers shared by the toolkit's GUIs (rf4mod_gui, map_editor, cutscene_editor):
the no-live-resize PanedWindow, hover tips, filterable comboboxes, commit-on-leave
entries, a scrollable column, and destroy-safe after() scheduling."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


# ---- error log (the console window) -------------------------------------------------- #
# Failures that are the toolkit's own fault (a bug, an unexpected game build, a Python that
# cannot do the job) go to the console window start.bat keeps open, as one block with the
# traceback and the versions, so a bug report is a copy-paste. The GUI only says that it
# failed and where the details are. Problems the user can act on (a bad value, a file that
# is open elsewhere, "the game is not running") keep their message in the GUI.

_LOGGED = set()


def modkit_version():
    """'<commit> <date>' of the toolkit: VERSION (stamped by git archive into the release
    zip), else the working copy's git HEAD, else 'unknown'."""
    import pathlib
    import subprocess
    here = pathlib.Path(__file__).resolve().parent
    try:
        v = (here / "VERSION").read_text(encoding="utf-8").strip()
        if v and "$Format" not in v:
            return v
    except OSError:
        pass
    try:
        out = subprocess.run(["git", "-C", str(here), "log", "-1", "--format=%h %cs"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip() + " (working copy)"
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def log_error(context, exc=None, detail=None):
    """Write one error block to the console (stderr): when, the toolkit / Python / Windows
    versions, what was being done, `detail`, and the exception with its traceback."""
    import datetime
    import platform
    import struct
    import sys
    import traceback
    out = sys.stderr or sys.__stderr__
    lines = ["", "=" * 78,
             "RF4S modkit error  %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "while: %s" % context,
             "modkit %s | Python %s (%d-bit) | %s" % (
                 modkit_version(), platform.python_version(), struct.calcsize("P") * 8,
                 platform.platform())]
    if detail:
        lines.append(str(detail))
    if exc is not None:
        lines.append("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip())
    lines += ["=" * 78, "(copy everything between the lines into a bug report)", ""]
    text = "\n".join(lines)
    if out is not None:
        try:
            print(text, file=out, flush=True)
            return
        except (OSError, ValueError):
            pass
    try:                                    # no console (pythonw): keep it in a file instead
        import pathlib
        with open(pathlib.Path(__file__).resolve().parent / "modkit_errors.log", "a",
                  encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass


def is_user_error(exc):
    """True for a failure the user can act on, whose message is meant for them: the
    toolkit's own error types (rf4s_modkit.*), a bad value (ValueError) and file problems
    (OSError). Anything else -- KeyError, TypeError, AttributeError, ... -- is a bug."""
    if getattr(exc, "technical", False):
        return False
    mod = type(exc).__module__ or ""
    return (mod.startswith(("rf4s_modkit", "cutscene_editor", "map_editor"))
            or isinstance(exc, (ValueError, OSError)))


def err_text(exc, context=None):
    """The text a GUI shows for a failure: the message itself when the user can act on it,
    else a pointer to the console, where the full error is logged (once per exception)."""
    if is_user_error(exc):
        return str(exc)
    if id(exc) not in _LOGGED:
        _LOGGED.add(id(exc))
        if context is None:
            import inspect
            fr = inspect.currentframe().f_back
            context = "%s (%s)" % (fr.f_code.co_name, fr.f_code.co_filename.replace("\\", "/").rsplit("/", 1)[-1])
        log_error(context, exc)
    return ("%s -- this is a toolkit problem, not something you did. The details are in the "
            "console window (the black window start.bat opened): please copy them into a bug "
            "report." % (type(exc).__name__ + (": %s" % exc if str(exc) else "")))


def install_error_logging(root=None):
    """Send every error nothing else handles to the console log: Tk callbacks of `root`,
    the main thread and worker threads. The GUI keeps running."""
    import sys
    import threading

    def tk_hook(etype, value, tb):
        value.__traceback__ = tb
        if isinstance(value, OSError):          # a save / export / open that hit a file problem
            try:
                from tkinter import messagebox
                where = getattr(value, "filename", None)
                messagebox.showerror("Couldn't do that", "%s%s\n\nIs the file open in another "
                                     "program, read-only, or the disk full?" % (
                                         ("%s:\n" % where) if where else "", value.strerror or value))
                return
            except Exception:  # noqa: BLE001 -- no Tk left: log it as below
                pass
        log_error("a button / event handler", value)
    if root is not None:
        root.report_callback_exception = tk_hook

    def main_hook(etype, value, tb):
        value.__traceback__ = tb
        log_error("the program", value)
    sys.excepthook = main_hook

    def thread_hook(args):
        if args.exc_value is not None:
            log_error("background thread %s" % getattr(args.thread, "name", "?"), args.exc_value)
    threading.excepthook = thread_hook


# ---- dialogs open over the window you are working in ------------------------------------ #
# Tk's message / file / input dialogs default their parent to the MAIN window, so an error in
# the Cutscene Editor (a separate window) would pull the main window to the front. With this
# installed, a dialog called without parent= opens over the last window that had the focus.
_DIALOGS = {"messagebox": ("showinfo", "showwarning", "showerror", "askquestion", "askokcancel",
                           "askyesno", "askyesnocancel", "askretrycancel"),
            "filedialog": ("askopenfilename", "askopenfilenames", "asksaveasfilename",
                           "askdirectory", "askopenfile", "asksaveasfile"),
            "simpledialog": ("askstring", "askinteger", "askfloat")}
_last_window = None


def _note_focus(e):
    global _last_window
    try:
        _last_window = e.widget.winfo_toplevel()
    except (tk.TclError, AttributeError, KeyError):
        pass


def dialog_parent():
    """The window a parent-less dialog should open over: the last one that had the focus, if
    it is still on screen, else None (Tk's default)."""
    w = _last_window
    try:
        if w is not None and w.winfo_exists() and w.winfo_viewable():
            return w
    except tk.TclError:
        pass
    return None


def _with_parent(fn):
    def call(*args, **kw):
        if kw.get("parent") is None:
            p = dialog_parent()
            if p is not None:
                kw["parent"] = p
        return fn(*args, **kw)
    call.__wrapped__ = fn
    call._rf4_parented = True
    return call


def install_dialog_parents(root):
    """Remember which window has the focus and default every standard dialog's parent to it."""
    import importlib
    root.bind_all("<FocusIn>", _note_focus, add="+")
    for mod_name, names in _DIALOGS.items():
        mod = importlib.import_module("tkinter." + mod_name)
        for name in names:
            fn = getattr(mod, name, None)
            if fn is not None and not getattr(fn, "_rf4_parented", False):
                setattr(mod, name, _with_parent(fn))


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


def wheel_handler(scroll, per_notch):
    """A <MouseWheel> / <Shift-MouseWheel> handler that scrolls in proportion to the wheel delta:
    one mouse notch (delta 120) scrolls `per_notch` units, and a trackpad's many small deltas add
    up smoothly in both directions (Tk's own `-delta/120` rounds them to 0 one way and to a
    whole step the other). scroll(n) moves n units (negative = up / left)."""
    acc = [0.0]

    def handler(e):
        acc[0] -= e.delta / 120 * per_notch
        n = int(acc[0])                 # toward 0; the remainder carries into the next event
        if n:
            acc[0] -= n
            scroll(n)
        return "break"
    return handler


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

    pending = {"id": None}

    def run_refocus():
        pending["id"] = None
        refocus()

    def on_destroy(e):
        if e.widget is focused["w"]:
            focused["w"] = None
            if pending["id"] is None:
                pending["id"] = frame.after_idle(run_refocus)
    frame.bind_class(tag, "<Destroy>", on_destroy, add="+")

    def on_frame_gone(e):
        # the whole scope is going (a window closing): its children went first and may have
        # queued a refocus -- drop it, or Tk runs it after the frame's command is gone
        if e.widget is frame and pending["id"] is not None:
            try:
                frame.after_cancel(pending["id"])
            except tk.TclError:
                pass
            pending["id"] = None
    frame.bind("<Destroy>", on_frame_gone, add="+")

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


DEFAULT_LIST_ROWS = 5000


def list_rows():
    """How many rows the big lists show before 'search to narrow' (setting "list_rows")."""
    try:
        from rf4s_modkit import gamepaths
        return max(100, int(gamepaths.get_setting("list_rows", DEFAULT_LIST_ROWS)))
    except (TypeError, ValueError, ImportError):
        return DEFAULT_LIST_ROWS


def combo_step(widget, d):
    """Pick the value `d` steps from the current one in a combobox and apply it at once
    (<<ComboboxSelected>>, as a click in the list would). The current text not in the list:
    Down picks the first value, Up the last. Returns the new value, or None."""
    try:
        if str(widget.cget("state")) == "disabled":
            return None
        if hasattr(widget, "load"):             # a FilterCombo hands Tk its list on demand
            widget.load()
        vals = list(widget.cget("values"))
    except tk.TclError:
        return None
    if not vals:
        return None
    cur = widget.get()
    i = vals.index(cur) if cur in vals else (-1 if d > 0 else len(vals))
    j = min(max(i + d, 0), len(vals) - 1)
    if j == i:
        return None
    widget.set(vals[j])
    widget.event_generate("<<ComboboxSelected>>")
    return vals[j]


def install_combo_keys(root):
    """Up / Down in any combobox step to the previous / next value and apply it at once,
    instead of opening the list; Alt+Down still opens it."""
    root.bind_class("TCombobox", "<Down>", lambda e: (combo_step(e.widget, 1), "break")[1])
    root.bind_class("TCombobox", "<Up>", lambda e: (combo_step(e.widget, -1), "break")[1])
    root.bind_class("TCombobox", "<Alt-Down>",
                    lambda e: (e.widget.tk.call("ttk::combobox::Post", e.widget), "break")[1])


class FilterCombo(ttk.Combobox):
    """A combobox whose list narrows to the entries containing what was typed (any word,
    case-insensitive). Picking an entry or pressing Enter calls on_pick(text)."""

    # The list goes to Tk only when it is needed (the dropdown opens, or Up / Down steps
    # through it): handing Tk thousands of entries per combobox made forms with many of them
    # slow to open (a 13-case SWITCH: 15 statement pickers, ~1.5 s).

    def __init__(self, parent, values, on_pick=None, width=30, **kw):
        # `values`: the entries, or a function that makes them (called the first time the
        # list is needed, for lists that are slow to build)
        self._make = values if callable(values) else None
        self._list = None if callable(values) else list(values)
        self._shown = None                # what Tk holds: None (nothing yet), "all", "filtered"
        self._var = kw.pop("textvariable", None) or tk.StringVar()
        super().__init__(parent, textvariable=self._var, values=(), width=width,
                         height=20, postcommand=self.load, **kw)
        self._on_pick = on_pick
        self.bind("<KeyRelease>", self._filter)
        self.bind("<<ComboboxSelected>>", self._picked)
        self.bind("<Return>", self._picked)
        self.bind("<FocusOut>", self._restore)
        self._commit = lambda: None       # picks commit immediately; nothing pending

    @property
    def var(self):
        return self._var

    @property
    def _all(self):
        if self._list is None:
            self._list = list(self._make())
        return self._list

    def values(self):
        """Every entry (the full list, whatever the dropdown shows now)."""
        return list(self._all)

    def load(self):
        """Give Tk the full list unless it already shows it or a typed filter's result."""
        if self._shown is None:
            self.configure(values=self._all)
            self._shown = "all"

    def set_values(self, values):
        self._make = values if callable(values) else None
        self._list = None if callable(values) else list(values)
        self.configure(values=())
        self._shown = None

    def _filter(self, e):
        if e.keysym in ("Return", "KP_Enter", "Up", "Down", "Escape", "Tab"):
            return
        words = self._var.get().lower().split()
        if not words:
            self._shown = None
            self.load()
            return
        vals = [v for v in self._all if all(w in v.lower() for w in words)]
        self.configure(values=vals[:400])
        self._shown = "filtered"

    def _reset(self):
        if self._shown == "filtered":     # back to the full list the next time it opens
            self.configure(values=())
            self._shown = None

    def _picked(self, _e=None):
        self._reset()
        if self._on_pick:
            self._on_pick(self._var.get())

    def _restore(self, _e=None):
        self._reset()


class CellEdit:
    """Spreadsheet-style editing of a ttk.Treeview's cells, instead of a form under the table.

    Click a cell to put the cell cursor (an outline) on it, then type to replace its value, or
    press F2 / Enter or double-click to edit what is there. In the edit box Enter keeps the
    value, Tab keeps it and moves to the next cell, Esc throws it away. Left / Right move the
    cursor between the editable columns, Up / Down between the rows. When the edited row is
    one of several selected rows, the viewer's put() may apply the value to all of them
    (`targets(iid)`).

    `cols` maps a column id to a dict:
      get(iid) -> str     the text the edit box starts with
      put(iid, text)      store the typed text (raise an error with a message to refuse it);
                          the viewer refills the tree itself
      choices             optional: the entries of a suggestion list (a list of str, or a
                          function returning one) shown under the cell while it is edited;
                          typing narrows it, Up / Down move the highlight, Enter takes it
      choices_for(iid)    optional, instead of choices: per row (None = a plain edit box)
      action(iid)         optional: a dialog instead of an edit box (bit sets, seasons ...)
      can(iid) -> bool    optional: whether this row's cell can be edited

    Build it after the table's scroll bars, so the outline follows scrolling."""

    COLOR = "#f08c00"                       # shows on a selected (blue) row and on a plain one

    def __init__(self, tv, cols, title="Edit failed"):
        self.tv, self.cols, self.title = tv, cols, title
        self.cur = None                         # (iid, column) under the cell cursor
        self.box = None                         # the open edit box
        self._outline = [tk.Frame(tv, background=self.COLOR, width=2, height=2) for _ in range(4)]
        for seq, fn in (("<ButtonRelease-1>", self._click), ("<Double-Button-1>", self._dbl),
                        ("<<TreeviewSelect>>", self._selected), ("<Key>", self._key),
                        ("<Configure>", lambda _e: self.redraw())):
            tv.bind(seq, fn, add="+")
        for seq, fn in (("<F2>", lambda _e: self._edit_key()), ("<Return>", lambda _e: self._edit_key()),
                        ("<KP_Enter>", lambda _e: self._edit_key()),
                        ("<BackSpace>", lambda _e: self._edit_key("")),
                        ("<Left>", lambda _e: self.move(-1)), ("<Right>", lambda _e: self.move(1)),
                        ("<Tab>", lambda _e: self.move(1)), ("<Shift-Tab>", lambda _e: self.move(-1))):
            tv.bind(seq, fn)
        for opt in ("yscrollcommand", "xscrollcommand"):
            self._follow(opt)

    # ---- the cell cursor ------------------------------------------------------------------
    def _follow(self, opt):
        orig = self.tv.tk.splitlist(str(self.tv.cget(opt)))

        def cmd(*a):
            if orig:
                self.tv.tk.call(*orig, *a)
            self.redraw()
        self.tv.configure(**{opt: cmd})

    def _shown(self):
        dc = [str(c) for c in self.tv["displaycolumns"]]
        return [str(c) for c in self.tv["columns"]] if dc in ([], ["#all"]) else dc

    def editable(self):
        """The editable columns in the order they are shown."""
        return [c for c in self._shown() if c in self.cols]

    def _col_at(self, x):
        cid = self.tv.identify_column(x)
        try:
            return self._shown()[int(cid[1:]) - 1]
        except (ValueError, IndexError):
            return None

    def redraw(self):
        for f in self._outline:
            f.place_forget()
        if self.cur is None or self.box is not None:
            return
        iid, col = self.cur
        try:
            bb = self.tv.bbox(iid, col) if self.tv.exists(iid) else ""
        except tk.TclError:
            bb = ""
        if not bb:
            return
        x, y, w, h = bb
        for f, (fx, fy, fw, fh) in zip(self._outline, ((x, y, w, 2), (x, y + h - 2, w, 2),
                                                       (x, y, 2, h), (x + w - 2, y, 2, h))):
            f.place(x=fx, y=fy, width=fw, height=fh)

    def _selected(self, _e=None):
        f = self.tv.focus()
        cols = self.editable()
        if not f or not cols:
            return
        col = self.cur[1] if self.cur and self.cur[1] in cols else cols[0]
        self.cur = (f, col)
        self.tv.after_idle(self.redraw)

    def _click(self, e):
        if self.tv.identify_region(e.x, e.y) != "cell":
            return
        row, col = self.tv.identify_row(e.y), self._col_at(e.x)
        if row and col in self.cols:
            self.cur = (row, col)
            self.redraw()

    def move(self, d):
        """Move the cell cursor d editable columns sideways (it stays inside the row)."""
        cols = self.editable()
        if self.cur is None or not cols:
            return None
        i = cols.index(self.cur[1]) if self.cur[1] in cols else 0
        self.cur = (self.cur[0], cols[min(max(i + d, 0), len(cols) - 1)])
        self.tv.see(self.cur[0])
        self.redraw()
        return "break"

    def targets(self, iid):
        """The rows an edit of `iid` applies to: the whole selection when iid is part of it."""
        sel = list(self.tv.selection())
        return sel if iid in sel and len(sel) > 1 else [iid]

    # ---- the edit box ---------------------------------------------------------------------
    def _dbl(self, e):
        row, col = self.tv.identify_row(e.y), self._col_at(e.x)
        if row and col in self.cols:
            self.cur = (row, col)
            self.edit(row, col)
            return "break"
        return None

    def _key(self, e):
        if self.box is not None or self.cur is None or e.state & 0x20004:     # Ctrl / Alt
            return None
        if len(e.char) == 1 and e.char.isprintable():
            self.edit(initial=e.char)
            return "break"
        return None

    def _edit_key(self, initial=None):
        if self.cur is None:
            return None
        self.edit(initial=initial)
        return "break"

    def edit(self, iid=None, col=None, initial=None):
        """Open the edit box on a cell (the cursor's by default); `initial` replaces its text."""
        if self.box is not None:
            self.finish(True)
        if iid is None or col is None:
            if self.cur is None:
                return
            iid, col = self.cur
        spec = self.cols.get(col)
        if spec is None or not self.tv.exists(iid) or (spec.get("can") and not spec["can"](iid)):
            return
        self.cur = (iid, col)
        if spec.get("action"):
            spec["action"](iid)
            return
        self.tv.see(iid)
        self.tv.update_idletasks()
        bb = self.tv.bbox(iid, col)
        if not bb:
            return
        x, y, w, h = bb
        start = spec["get"](iid)
        var = tk.StringVar(value=start if initial is None else initial)
        choices = spec["choices_for"](iid) if "choices_for" in spec else spec.get("choices")
        box = ttk.Entry(self.tv, textvariable=var)
        if choices is not None:
            w = max(w, 240)
        x = min(x, max(0, self.tv.winfo_width() - w))
        self.box, self._var, self._start, self._at = box, var, start, (iid, col)
        self._list = None
        self.redraw()
        box.place(x=x, y=y, width=w, height=h)
        box.focus_set()
        if initial is None:
            box.select_range(0, "end")
        else:
            box.icursor("end")
        if choices is not None:
            self._open_list(list(choices() if callable(choices) else choices), typed=initial is not None)
        for seq, keep, d in (("<Return>", True, 0), ("<KP_Enter>", True, 0), ("<Tab>", True, 1),
                             ("<Shift-Tab>", True, -1), ("<Escape>", False, 0)):
            box.bind(seq, lambda _e, k=keep, d=d: (self.finish(k, d), "break")[1], add="+")
        box.bind("<FocusOut>", lambda _e: self.tv.after(30, self._focus_left), add="+")

    # ---- the suggestion list: open under the cell while it is edited, narrowed as you type;
    # the edit box keeps the keyboard (Up / Down move the highlight, Enter / Tab take it, a click
    # picks an entry) ---------------------------------------------------------------------------
    LIST_ROWS = 12
    LIST_MAX = 5000                         # every item fits (the current one gets highlighted)

    def _open_list(self, values, typed):
        box = self.box
        top = tk.Toplevel(box)
        top.wm_overrideredirect(True)
        try:
            top.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        lb = tk.Listbox(top, height=self.LIST_ROWS, activestyle="dotbox", exportselection=False,
                        takefocus=0, highlightthickness=1, borderwidth=0)
        sb = ttk.Scrollbar(top, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        lb.pack(side="left", fill="both", expand=True)
        st = {"all": values, "shown": [], "moved": False}
        self._list = (top, lb, st)

        def fill(narrow):
            words = self._var.get().lower().split() if narrow else []
            shown = [v for v in st["all"] if all(wd in v.lower() for wd in words)][:self.LIST_MAX]
            st["shown"] = shown
            lb.delete(0, "end")
            for v in shown:
                lb.insert("end", v)
            pick = None
            if shown:
                cur = self._var.get().strip()
                exact = [k for k, v in enumerate(shown)
                         if v.lower() == cur.lower() or (cur.isdigit() and v.endswith(f"({cur})"))]
                pick = exact[0] if exact else (0 if narrow else None)
            highlight(pick)
            place()

        def highlight(k):
            lb.selection_clear(0, "end")
            if k is not None and 0 <= k < lb.size():
                lb.selection_set(k)
                lb.activate(k)
                lb.see(k)

        def place():
            if not st["shown"]:
                top.withdraw()
                return
            box.update_idletasks()
            bx, by, bw, bh = box.winfo_rootx(), box.winfo_rooty(), box.winfo_width(), box.winfo_height()
            rows = min(self.LIST_ROWS, len(st["shown"]))
            lb.configure(height=rows)
            top.update_idletasks()
            lh = top.winfo_reqheight()
            sh = box.winfo_screenheight()
            y = by + bh if by + bh + lh <= sh else max(0, by - lh)
            import tkinter.font as tkfont
            f = tkfont.Font(font=lb.cget("font"))
            lw = max(bw, min(640, max(f.measure(v) for v in st["shown"][:600]) + 40))
            lw = min(lw, box.winfo_screenwidth())
            lx = min(bx, box.winfo_screenwidth() - lw)
            top.geometry(f"{lw}x{lh}+{lx}+{y}")
            top.deiconify()
            top.lift()

        def step(d):
            if not st["shown"]:
                return "break"
            sel = lb.curselection()
            k = (sel[0] + d) if sel else (0 if d > 0 else len(st["shown"]) - 1)
            highlight(min(max(k, 0), len(st["shown"]) - 1))
            st["moved"] = True
            return "break"

        def typed_key(e):
            if e.keysym in ("Up", "Down", "Prior", "Next", "Return", "KP_Enter", "Tab", "Escape",
                            "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"):
                return
            st["moved"] = False
            fill(True)

        def click(e):
            k = lb.nearest(e.y)
            if 0 <= k < len(st["shown"]):
                highlight(k)                    # finish() takes the highlighted entry
                self.finish(True)
            return "break"
        box.bind("<Down>", lambda _e: step(1))
        box.bind("<Up>", lambda _e: step(-1))
        box.bind("<Next>", lambda _e: step(self.LIST_ROWS))
        box.bind("<Prior>", lambda _e: step(-self.LIST_ROWS))
        box.bind("<KeyRelease>", typed_key, add="+")
        lb.bind("<ButtonPress-1>", click)
        lb.bind("<MouseWheel>", lambda e: (lb.yview_scroll(-1 if e.delta > 0 else 1, "units"), "break")[1])
        fill(typed)

    def _take_highlight(self):
        """The highlighted suggestion goes into the edit box (Enter / Tab)."""
        if self._list is None:
            return
        _top, lb, st = self._list
        sel = lb.curselection()
        if sel and sel[0] < len(st["shown"]):
            self._var.set(st["shown"][sel[0]])

    def _close_list(self):
        if self._list is not None:
            try:
                self._list[0].destroy()
            except tk.TclError:
                pass
            self._list = None

    def _focus_left(self):
        if self.box is None:
            return
        try:
            w = self.tv.focus_get()
        except (KeyError, tk.TclError):
            return
        if w is None:                           # another program: hide the list, keep editing
            if self._list is not None:
                self._list[0].withdraw()
            return
        if str(w).startswith(str(self.box)):
            return
        self.finish(True)

    def finish(self, keep, move=0):
        """Close the edit box; keep = store what was typed (a refused value shows why)."""
        box = self.box
        if box is None:
            return
        if keep:
            self._take_highlight()
        self._close_list()
        self.box = None
        text, (iid, col) = self._var.get(), self._at
        box.destroy()
        self.tv.focus_set()
        if keep and text != self._start:
            try:
                self.cols[col]["put"](iid, text)
            except Exception as e:  # noqa: BLE001 - the viewer's own message
                from tkinter import messagebox
                messagebox.showerror(self.title, err_text(e, f"{self.title}: {col}"))
        if self.tv.exists(iid):
            self.tv.focus(iid)
        if move:
            self.move(move)
        self.tv.after_idle(self.redraw)

    def set(self, iid, col, text):
        """Store `text` in a cell as typed there (errors are raised, not shown) -- for scripts
        and the selftest."""
        self.cols[col]["put"](str(iid), str(text))


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


class TabBar(ttk.Frame):
    """A row of tabs that scrolls (ttk.Notebook squeezes tabs it has no room for): the ◀ ▶
    buttons and the mouse wheel scroll it, ▼ lists every tab to pick one, each tab's ×
    or a middle click closes it. Tabs are keyed by any hashable; the host shows the page.
    on_select(key) / on_close(key) / on_menu(key, event) are the host's callbacks."""
    _LIGHT = ("#dddddd", "#ffffff", "#ebebeb", "#b4b4b4", "#707070")
    _DARK = ("#2a2a31", "#3a3a44", "#34343c", "#1f1f24", "#8a8a94")     # (guitheme's dark mode)

    def _pal(self, i):
        try:
            import guitheme
            return (self._DARK if guitheme.is_dark() else self._LIGHT)[i]
        except ImportError:
            return self._LIGHT[i]

    BG = property(lambda self: self._pal(0))
    SEL = property(lambda self: self._pal(1))
    HOVER = property(lambda self: self._pal(2))
    LINE = property(lambda self: self._pal(3))
    DIM = property(lambda self: self._pal(4))

    def __init__(self, parent, on_select, on_close, on_menu=None):
        super().__init__(parent)
        self._on_select, self._on_close, self._on_menu = on_select, on_close, on_menu
        self._tabs = {}                          # key -> (frame, label, close label)
        self._sel = None
        self._drop = ttk.Button(self, text="▼", width=2, command=self._post_list)
        self._drop.pack(side="right")
        Tip(self._drop, "Every open tab: pick one to go to it.")
        self._next = ttk.Button(self, text="▶", width=2, command=lambda: self.scroll(1))
        self._next.pack(side="right")
        self._prev = ttk.Button(self, text="◀", width=2, command=lambda: self.scroll(-1))
        self._prev.pack(side="left")
        self.canvas = tk.Canvas(self, height=1, highlightthickness=0, bd=0, xscrollincrement=40)
        self.canvas.pack(side="left", fill="x", expand=True)
        self.inner = tk.Frame(self.canvas, bg=self.LINE)
        self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._sync)
        self.canvas.bind("<Configure>", self._sync)
        self._wheel(self.canvas)
        self._menu = tk.Menu(self, tearoff=False)
        self.bind("<<ThemeChanged>>", lambda _e: self._retheme(), add="+")   # light / dark switched

    def _retheme(self):
        self.inner.configure(bg=self.LINE)
        for key, (_f, _lbl, x) in self._tabs.items():
            x.configure(fg=self.DIM)
            self._paint(key)

    # ---- tabs ---------------------------------------------------------------------- #
    def add(self, key, text):
        f = tk.Frame(self.inner, bg=self.BG)
        lbl = tk.Label(f, text=text, bg=self.BG, padx=8, pady=3)
        x = tk.Label(f, text="×", bg=self.BG, fg=self.DIM, padx=4)
        lbl.pack(side="left")
        x.pack(side="left")
        f.pack(side="left", padx=(0, 1), pady=(1, 0))
        for w in (f, lbl):
            w.bind("<Button-1>", lambda _e, k=key: self._pick(k))
            w.bind("<Button-2>", lambda _e, k=key: self._on_close(k))
            w.bind("<Enter>", lambda _e, k=key: self._paint(k, hover=True))
            w.bind("<Leave>", lambda _e, k=key: self._paint(k))
            if self._on_menu:
                w.bind("<Button-3>", lambda e, k=key: self._on_menu(k, e))
            self._wheel(w)
        x.bind("<Button-1>", lambda _e, k=key: self._on_close(k))
        x.bind("<Enter>", lambda _e: x.config(fg="#c42b1c"))
        x.bind("<Leave>", lambda _e: x.config(fg=self.DIM))
        self._tabs[key] = (f, lbl, x)
        self._paint(key)

    def remove(self, key):
        t = self._tabs.pop(key, None)
        if t is not None:
            t[0].destroy()
        if self._sel == key:
            self._sel = None

    def set_text(self, key, text):
        if key in self._tabs:
            self._tabs[key][1].config(text=text)

    def text(self, key):
        return self._tabs[key][1].cget("text") if key in self._tabs else None

    def keys(self):
        return list(self._tabs)                  # in tab order (dicts keep insertion order)

    def select(self, key):
        """Mark `key` as the shown tab and scroll it into view (no on_select callback)."""
        old, self._sel = self._sel, key
        for k in (old, key):
            if k in self._tabs:
                self._paint(k)
        self.after_idle(lambda: self.see(key))

    def selected(self):
        return self._sel

    def _pick(self, key):
        if key != self._sel:
            self._on_select(key)

    def _paint(self, key, hover=False):
        if key not in self._tabs:
            return
        f, lbl, x = self._tabs[key]
        bg = self.SEL if key == self._sel else (self.HOVER if hover else self.BG)
        for w in (f, lbl, x):
            w.config(bg=bg)

    # ---- scrolling ----------------------------------------------------------------- #
    def _wheel(self, w):
        w.bind("<MouseWheel>", lambda e: self.scroll(-1 if e.delta > 0 else 1))
        w.bind("<Shift-MouseWheel>", lambda e: self.scroll(-1 if e.delta > 0 else 1))

    def scroll(self, direction):
        self.canvas.xview_scroll(direction * 3, "units")
        self._arrows()

    def see(self, key):
        """Scroll so tab `key` is fully visible."""
        if key not in self._tabs:
            return
        try:
            self.update_idletasks()
            f = self._tabs[key][0]
            total = max(self.inner.winfo_width(), 1)
            view = self.canvas.winfo_width()
            left = self.canvas.canvasx(0)
            x0, x1 = f.winfo_x(), f.winfo_x() + f.winfo_width()
            if x0 < left:
                self.canvas.xview_moveto(x0 / total)
            elif x1 > left + view:
                self.canvas.xview_moveto(max(x1 - view, 0) / total)
            self._arrows()
        except tk.TclError:
            pass

    def _sync(self, _e=None):
        self.canvas.configure(height=self.inner.winfo_reqheight(),
                              scrollregion=(0, 0, self.inner.winfo_reqwidth(), 1))
        self._arrows()

    def _arrows(self):
        lo, hi = self.canvas.xview()
        self._prev.state(["!disabled"] if lo > 0.0005 else ["disabled"])
        self._next.state(["!disabled"] if hi < 0.9995 else ["disabled"])

    def _post_list(self):
        m = self._menu
        m.delete(0, "end")
        for k, (_f, lbl, _x) in self._tabs.items():
            mark = "✓  " if k == self._sel else "     "
            m.add_command(label=mark + lbl.cget("text"), command=lambda k=k: self._pick(k))
        b = self._drop
        try:
            m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
        finally:
            m.grab_release()


def monitor_rect(widget, x, y):
    """(left, top, right, bottom) of the work area of the monitor holding screen point
    (x, y): the Windows API when available (so a second monitor counts), else the screen."""
    try:
        import sys
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
            user32 = ctypes.windll.user32
            user32.MonitorFromPoint.restype = wintypes.HMONITOR
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            mon = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)   # NEAREST
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if mon and user32.GetMonitorInfoW(mon, ctypes.byref(info)):
                r = info.rcWork
                return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()


def tip_wraplength(widget, x, y, want=520):
    """A tooltip's wrap width: `want` pixels, less on a monitor narrower than that."""
    left, _t, right, _b = monitor_rect(widget, x, y)
    return max(120, min(want, right - left - 24))


def place_popup(top, x, y, above=None, gap=4):
    """Show a borderless popup with its top-left at (x, y), kept on the monitor: moved left
    when it would cross the right edge, and above `above` (a y the popup's bottom may sit
    at, e.g. the top of the hovered widget) -- or just up -- when it would cross the bottom."""
    top.update_idletasks()
    w, h = top.winfo_reqwidth(), top.winfo_reqheight()
    left, top_edge, right, bottom = monitor_rect(top, x, y)
    if x + w > right - gap:
        x = right - gap - w
    if y + h > bottom - gap:
        y = (above - h - gap) if above is not None else bottom - gap - h
    x = max(left + gap, x)
    y = max(top_edge + gap, y)
    top.wm_geometry(f"+{int(x)}+{int(y)}")


class Tip:
    """Hover help for a widget (shown after a short delay; wrapped and kept on screen)."""

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
        self._top.withdraw()                    # placed once its size is known
        x = self.w.winfo_rootx() + 8
        y = self.w.winfo_rooty() + self.w.winfo_height() + 4
        tk.Label(self._top, text=text, justify="left", bg="#222", fg="#eee", font=("Consolas", 8),
                 bd=1, relief="solid", padx=4, pady=2,
                 wraplength=tip_wraplength(self.w, x, y)).pack()
        place_popup(self._top, x, y, above=self.w.winfo_rooty())
        self._top.deiconify()

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
        self._n -= e.delta / 120 * 2        # fractional: a trackpad's small steps add up
        if not self._pending:
            self._pending = True
            later(self, self._flush, 15)

    def _flush(self):
        n = int(self._n)
        self._n, self._pending = self._n - n, False
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
