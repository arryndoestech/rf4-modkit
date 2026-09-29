"""guiscale.py -- the toolkit's text size (Options -> Display), applied live.

The setting (settings.json "ui_scale", percent) scales every font without a restart:
  * Tk's named fonts (TkDefaultFont, TkTextFont, ...) get the scaled size;
  * every widget whose font the code set by hand (("Segoe UI", 9) ...) and every Text /
    Treeview tag font gets the same font at the scaled size in pixels, as each widget appears
    (the original is remembered, so 100 % restores it);
  * list rows (Treeview rowheight) grow to fit, in the light and the dark theme.
Tk's own point scaling is left alone: a font spec in points realised later is converted the
moment its widget is shown.
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

SCALES = (100, 110, 125, 150, 175, 200)

_state = {"root": None, "factor": 1.0, "bound": False, "named": {}, "orig": {}, "specs": {},
          "row": None}


def setting():
    """The saved text size in percent (100 = normal)."""
    try:
        from rf4s_modkit import gamepaths
        v = int(gamepaths.get_setting("ui_scale", 100))
    except (TypeError, ValueError, ImportError):
        v = 100
    return v if 50 <= v <= 300 else 100


def row_height():
    """The list row height that fits the text size, or None at 100 %."""
    return _state["row"]


def _pixels(root, size):
    """A font size (points > 0, pixels < 0) in pixels at the base scaling."""
    size = int(size)
    if size < 0:
        return -size
    return size * float(root.tk.call("tk", "scaling"))


def _scaled_spec(root, spec, f):
    """`spec` (any font description) at f times its size, as an explicit pixel-size spec."""
    key = (spec, f)
    if key in _state["specs"]:
        return _state["specs"][key]
    try:
        a = root.tk.call("font", "actual", spec)
    except tk.TclError:
        _state["specs"][key] = spec
        return spec
    a = dict(zip(a[::2], a[1::2]))
    px = max(4, int(round(_pixels(root, a["-size"]) * f)))
    parts = ["{%s}" % a["-family"], str(-px), str(a["-weight"]), str(a["-slant"])]
    if int(a.get("-underline", 0)):
        parts.append("underline")
    if int(a.get("-overstrike", 0)):
        parts.append("overstrike")
    out = " ".join(parts)
    _state["specs"][key] = out
    return out


def _is_named(root, spec):
    try:
        return spec in root.tk.splitlist(root.tk.call("font", "names"))
    except tk.TclError:
        return False


def _scale_widget(w):
    root, f = _state["root"], _state["factor"]
    path = str(w)
    orig = _state["orig"].setdefault(path, {})
    try:
        keys = w.keys()
    except tk.TclError:
        return
    if "font" in keys:
        try:
            cur = str(w.cget("font"))
        except tk.TclError:
            cur = ""
        base = orig.get("font", cur)
        if base and not _is_named(root, base):
            new = _scaled_spec(root, base, f) if f != 1.0 else base
            if new != cur:
                orig.setdefault("font", cur)
                try:
                    w.configure(font=new)
                except tk.TclError:
                    pass
    cls = w.winfo_class()
    if cls in ("Text", "Treeview"):
        try:
            tags = w.tk.splitlist(w.tk.call(w._w, "tag", "names"))
        except tk.TclError:
            tags = ()
        for t in tags:
            try:
                cur = str(w.tag_cget(t, "font") if cls == "Text" else (w.tag_configure(t, "font") or ""))
            except tk.TclError:
                continue
            key = "tag:" + t
            base = orig.get(key, cur)
            if not base or _is_named(root, base):
                continue
            new = _scaled_spec(root, base, f) if f != 1.0 else base
            if new != cur:
                orig.setdefault(key, cur)
                try:
                    w.tag_configure(t, font=new)
                except tk.TclError:
                    pass
    if not orig:
        _state["orig"].pop(path, None)


def _walk(w):
    yield w
    for c in w.winfo_children():
        yield from _walk(c)


def _on_map(e):
    if isinstance(e.widget, tk.Misc) and (_state["factor"] != 1.0 or str(e.widget) in _state["orig"]):
        _scale_widget(e.widget)


def _rows(root):
    """Treeview rows that fit the text: in the current ttk theme (the dark theme asks again)."""
    f = _state["factor"]
    if f == 1.0:
        _state["row"] = None
        return
    line = tkfont.nametofont("TkDefaultFont", root).metrics("linespace")
    _state["row"] = line + max(4, int(4 * f))
    ttk.Style(root).configure("Treeview", rowheight=_state["row"])


def apply(root=None, percent=None):
    """Set the text size of every window of the app (the saved setting by default)."""
    root = root or _state["root"]
    if root is None:
        return
    f = (percent if percent is not None else setting()) / 100.0
    _state["factor"] = f
    for name in root.tk.splitlist(root.tk.call("font", "names")):
        fo = tkfont.nametofont(name, root)
        base = _state["named"].setdefault(name, int(fo.cget("size")))
        fo.configure(size=base if f == 1.0 else -max(4, int(round(_pixels(root, base) * f))))
    _rows(root)
    if f == 1.0:
        try:
            ttk.Style(root).configure("Treeview", rowheight="")
        except tk.TclError:
            pass
    for w in _walk(root):
        _scale_widget(w)
    if f == 1.0:
        _state["orig"].clear()


def install(root):
    """Apply the saved text size and scale windows as they open."""
    _state["root"] = root
    if not _state["bound"]:
        root.bind_all("<Map>", _on_map, add="+")
        _state["bound"] = True
    apply(root)


def set_percent(percent):
    """Save the choice and apply it to the running app."""
    from rf4s_modkit import gamepaths
    gamepaths.set_setting("ui_scale", int(percent))
    apply(percent=int(percent))
