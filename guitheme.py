"""guitheme.py -- light / dark appearance for every toolkit window.

One setting (settings.json "theme": "light", "dark" or "system" = follow Windows) drives all
the toolkit's windows. Dark mode:
  * ttk widgets: the "clam" theme with a dark palette (buttons, entries, lists, tabs ...);
  * plain Tk widgets (Text, Listbox, Canvas, Menu ...) and every colour the code sets by hand
    (grey hint text, red / blue notes, Treeview and Text tags) are adapted as each widget
    appears: dark text is lightened and light backgrounds darkened, keeping the hue, so the
    meaning of a colour survives;
  * Windows title bars are switched to their dark style.
Switching back restores every original colour. install(root) is called once per app.
"""
from __future__ import annotations

import colorsys
import tkinter as tk
from tkinter import ttk

MODES = ("light", "dark", "system")
LABELS = {"light": "Light", "dark": "Dark", "system": "Follow Windows"}

DARK = {
    "bg": "#1f1f24", "panel": "#26262c", "field": "#2c2c33", "fg": "#e4e4ea", "muted": "#a8a8b2",
    "border": "#3a3a44", "button": "#34343c", "button_active": "#42424c", "select": "#35598f",
    "select_fg": "#ffffff", "disabled": "#76767f",
}

_state = {"root": None, "mode": "light", "base_theme": None, "orig": {}, "bound": False}

# widget options that are backgrounds / foregrounds
_BG = ("background", "activebackground", "selectbackground", "highlightbackground",
       "readonlybackground", "troughcolor", "disabledbackground", "inactiveselectbackground")
_FG = ("foreground", "activeforeground", "insertbackground", "selectforeground",
       "disabledforeground", "highlightcolor")


def setting():
    """The saved choice: 'light', 'dark' or 'system'."""
    try:
        from rf4s_modkit import gamepaths
        m = gamepaths.get_setting("theme", "light")
    except Exception:
        m = "light"
    return m if m in MODES else "light"


def windows_is_dark():
    """True when Windows apps use the dark theme (AppsUseLightTheme = 0)."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        v, _t = winreg.QueryValueEx(k, "AppsUseLightTheme")
        return v == 0
    except Exception:
        return False


def effective(mode=None):
    """'light' or 'dark' for a setting."""
    mode = mode or setting()
    if mode == "system":
        return "dark" if windows_is_dark() else "light"
    return mode


def is_dark():
    return _state["mode"] == "dark"


# ---- colour adaptation ------------------------------------------------------------------ #
def _rgb(widget, colour):
    try:
        r, g, b = widget.winfo_rgb(colour)
    except tk.TclError:
        return None
    return r / 65535.0, g / 65535.0, b / 65535.0


def _hex(r, g, b):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(x * 255))) for x in (r, g, b))


def adapt(widget, colour, role):
    """The dark-mode version of `colour` used as a background ('bg') or text ('fg')."""
    if not colour:
        return colour
    rgb = _rgb(widget, colour)
    if rgb is None:
        return colour
    h, l, s = colorsys.rgb_to_hls(*rgb)
    if role == "bg":
        if l <= 0.55:
            return colour                              # already dark
        if s < 0.12 and l >= 0.9:
            # the standard light window / field colours: exactly the dark palette's, so a
            # plain Tk widget matches the ttk frames around it
            return DARK["field"] if l >= 0.99 else DARK["bg"]
        l2, s2 = 0.11 + (1.0 - l) * 0.5, s * 0.55
    else:
        if l >= 0.6:
            return colour                              # already light
        l2, s2 = 0.93 - l * 0.45, min(1.0, s * 1.1)
    return _hex(*colorsys.hls_to_rgb(h, l2, s2))


def _remember(widget, key, value):
    _state["orig"].setdefault(str(widget), {}).setdefault(key, value)


def _adapt_widget(w):
    """Dark colours for one widget (its own options and its Treeview / Text tags)."""
    dark = is_dark()
    path = str(w)
    orig = _state["orig"].get(path, {})
    try:
        keys = w.keys()
    except tk.TclError:
        return
    is_ttk = w.winfo_class().startswith("T") and hasattr(w, "state") and isinstance(w, ttk.Widget)
    for opt in _BG + _FG:
        if opt not in keys:
            continue
        try:
            cur = str(w.cget(opt))
        except tk.TclError:
            continue
        if is_ttk and not cur:
            continue                                   # ttk: empty = the style's colour
        base = orig.get(opt, cur)
        new = adapt(w, base, "bg" if opt in _BG else "fg") if dark else base
        if new != cur:
            _remember(w, opt, cur)
            try:
                w.configure(**{opt: new})
            except tk.TclError:
                pass
    cls = w.winfo_class()
    if cls in ("Treeview", "Text"):
        try:                                           # (ttk.Treeview has no tag_names())
            tags = w.tk.splitlist(w.tk.call(w._w, "tag", "names"))
        except tk.TclError:
            tags = ()
        for t in tags:
            if cls == "Text" and t == "sel":
                continue
            for opt, role in (("foreground", "fg"), ("background", "bg")):
                try:
                    cur = str(w.tag_cget(t, opt) if cls == "Text" else (w.tag_configure(t, opt) or ""))
                except tk.TclError:
                    continue
                if not cur:
                    continue
                key = "tag:%s:%s" % (t, opt)
                base = orig.get(key, cur)
                new = adapt(w, base, role) if dark else base
                if new != cur:
                    _remember(w, key, cur)
                    try:
                        w.tag_configure(t, **{opt: new})
                    except tk.TclError:
                        pass


def _walk(w):
    yield w
    for c in w.winfo_children():
        yield from _walk(c)


def _titlebar(w):
    """Windows 10 / 11 dark title bar for a toplevel (DWMWA_USE_IMMERSIVE_DARK_MODE)."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(w.winfo_id())
        val = ctypes.c_int(1 if is_dark() else 0)
        for attr in (20, 19):                      # 20 on current builds, 19 on older Windows 10
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val),
                                                          ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass


def _on_map(e):
    w = e.widget
    if not isinstance(w, tk.Misc):
        return
    if isinstance(w, (tk.Tk, tk.Toplevel)):
        _titlebar(w)
    if is_dark() or str(w) in _state["orig"]:
        _adapt_widget(w)


# ---- ttk styles ------------------------------------------------------------------------ #
def _style_dark(root):
    p = DARK
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", background=p["bg"], foreground=p["fg"], fieldbackground=p["field"],
                 bordercolor=p["border"], darkcolor=p["bg"], lightcolor=p["panel"],
                 troughcolor=p["bg"], selectbackground=p["select"], selectforeground=p["select_fg"],
                 insertcolor=p["fg"], focuscolor=p["select"], arrowcolor=p["fg"])
    st.map(".", foreground=[("disabled", p["disabled"])], background=[("disabled", p["bg"])])
    st.configure("TButton", background=p["button"], bordercolor=p["border"])
    st.map("TButton", background=[("pressed", p["select"]), ("active", p["button_active"])])
    st.configure("TMenubutton", background=p["button"])
    st.map("TMenubutton", background=[("active", p["button_active"])], foreground=[("active", p["fg"])])
    # the map editor's tool row (Select / Paint / ...): radio buttons in the Toolbutton style
    st.configure("Toolbutton", background=p["bg"], foreground=p["fg"], bordercolor=p["border"])
    st.map("Toolbutton",
           background=[("selected", p["select"]), ("pressed", p["select"]), ("active", p["button_active"])],
           foreground=[("disabled", p["disabled"]), ("selected", p["select_fg"]), ("active", p["fg"])])
    st.map("TCombobox", background=[("active", p["button_active"])])
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        st.configure(w, fieldbackground=p["field"], foreground=p["fg"], insertcolor=p["fg"])
        st.map(w, fieldbackground=[("readonly", p["field"]), ("disabled", p["bg"])],
               foreground=[("disabled", p["disabled"])])
    st.configure("Treeview", background=p["field"], fieldbackground=p["field"], foreground=p["fg"])
    st.map("Treeview", background=[("selected", p["select"])], foreground=[("selected", p["select_fg"])])
    st.configure("Treeview.Heading", background=p["panel"], foreground=p["fg"])
    st.map("Treeview.Heading", background=[("active", p["button_active"])])
    st.configure("TNotebook", background=p["bg"], bordercolor=p["border"])
    st.configure("TNotebook.Tab", background=p["panel"], foreground=p["muted"])
    st.map("TNotebook.Tab", background=[("selected", p["field"])], foreground=[("selected", p["fg"])])
    for w in ("TCheckbutton", "TRadiobutton"):
        st.configure(w, indicatorbackground=p["field"], indicatorforeground=p["fg"])
        st.map(w, background=[("active", p["bg"])], indicatorbackground=[("selected", p["select"])])
    st.configure("TScrollbar", background=p["panel"], troughcolor=p["bg"], arrowcolor=p["fg"])
    st.configure("TLabelframe", background=p["bg"], bordercolor=p["border"])
    st.configure("TLabelframe.Label", background=p["bg"], foreground=p["fg"])
    st.configure("TProgressbar", background=p["select"], troughcolor=p["field"])
    st.configure("Sash", background=p["border"])
    # the combobox's drop-down list and plain Tk widgets made from now on
    for pat, val in (("*TCombobox*Listbox.background", p["field"]),
                     ("*TCombobox*Listbox.foreground", p["fg"]),
                     ("*TCombobox*Listbox.selectBackground", p["select"]),
                     ("*TCombobox*Listbox.selectForeground", p["select_fg"]),
                     ("*Menu.background", p["panel"]), ("*Menu.foreground", p["fg"]),
                     ("*Menu.activeBackground", p["select"]), ("*Menu.activeForeground", p["select_fg"])):
        root.option_add(pat, val)


def _style_light(root):
    st = ttk.Style(root)
    if _state["base_theme"] and st.theme_use() != _state["base_theme"]:
        st.theme_use(_state["base_theme"])
    root.option_clear()


def apply(root=None, mode=None):
    """Switch every window of the app to `mode` ('light' / 'dark' / 'system'; the saved
    setting by default)."""
    root = root or _state["root"]
    if root is None:
        return
    new = effective(mode)
    _state["mode"] = new
    if new == "dark":
        _style_dark(root)
    else:
        _style_light(root)
    frame_bg = ttk.Style(root).lookup("TFrame", "background")
    for w in _walk(root):
        _adapt_widget(w)
        if isinstance(w, (tk.Tk, tk.Toplevel)):
            _titlebar(w)
        if w.winfo_class() == "Panedwindow" and frame_bg:
            # guiutil.Paned copies the frame colour when it is made: give it the new one
            try:
                w.configure(background=frame_bg)
            except tk.TclError:
                pass
    if new == "light":
        _state["orig"].clear()
    # widgets that copied a theme colour when they were made re-read it on this event
    # (Tk's <<ThemeChanged>> only reaches ttk widgets)
    for w in _walk(root):
        try:
            w.event_generate("<<AppearanceChanged>>")
        except tk.TclError:
            pass


def install(root):
    """Remember the platform theme, apply the saved setting and adapt windows as they open."""
    _state["root"] = root
    if _state["base_theme"] is None:
        _state["base_theme"] = ttk.Style(root).theme_use()
    if not _state["bound"]:
        root.bind_all("<Map>", _on_map, add="+")
        _state["bound"] = True
    apply(root)


def set_mode(mode):
    """Save the choice and apply it to the running app."""
    from rf4s_modkit import gamepaths
    gamepaths.set_setting("theme", mode)
    apply(mode=mode)
