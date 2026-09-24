"""Small Tk helpers shared by the toolkit's GUIs (rf4mod_gui, map_explorer, script_explorer)."""
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
