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


def combo_step(widget, d):
    """Pick the value `d` steps from the current one in a combobox and apply it at once
    (<<ComboboxSelected>>, as a click in the list would). The current text not in the list:
    Down picks the first value, Up the last. Returns the new value, or None."""
    try:
        if str(widget.cget("state")) == "disabled":
            return None
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


class TabBar(ttk.Frame):
    """A row of tabs that scrolls (ttk.Notebook squeezes tabs it has no room for): the ◀ ▶
    buttons and the mouse wheel scroll it, ▼ lists every tab to pick one, each tab's ×
    or a middle click closes it. Tabs are keyed by any hashable; the host shows the page.
    on_select(key) / on_close(key) / on_menu(key, event) are the host's callbacks."""
    BG, SEL, HOVER, LINE, DIM = "#dddddd", "#ffffff", "#ebebeb", "#b4b4b4", "#707070"

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
