"""shortcuts_help.py -- the Help window: every keyboard shortcut and mouse gesture of the toolkit.

The list is kept by hand next to the bindings (rf4mod_gui, map_editor, cutscene_editor,
text_tab, guiutil); selftest checks a sample of it against the real bindings.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# (tab, [(section or None, [(keys, what it does)])])
SHORTCUTS = [
    ("Explorer", [
        ("Tabs", [
            ("Ctrl+W", "close the current tab (asks if it has unsaved changes)"),
            ("Ctrl+Tab / Ctrl+Shift+Tab", "next / previous tab"),
            ("Click a tab", "show it"),
            ("Middle-click a tab, or its ×", "close it"),
            ("Right-click a tab", "Close / Close the other tabs"),
            ("Wheel over the tabs", "scroll the tab row"),
        ]),
        ("File list", [
            ("Click a file", "show it in the current tab"),
            ("Up / Down", "show the next / previous file in the same tab"),
            ("Double-click a file", "open it in a new tab"),
            ("Enter in Filter", "filter at once"),
        ]),
        ("Elsewhere", [
            ("Double-click a scene (a map's Events tab)", "open it in the Cutscene Editor"),
            ("Drag a gate or monster point (Gates picture)", "move it"),
        ]),
    ]),
    ("Map editor", [
        ("Anywhere in the editor", [
            ("Ctrl+S", "save over the game's files"),
            ("Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z)", "undo / redo"),
        ]),
        ("Tools (the map must have the keyboard: click it)", [
            ("V", "Select"), ("B", "Paint"), ("G", "Fill"), ("R", "Rectangle"),
            ("I", "Pick (takes a tile's value, then back to the paint tool)"),
            ("A", "Add"), ("W", "Warp"),
            ("[ / ]", "smaller / bigger brush"),
        ]),
        ("Editing (the map has the keyboard)", [
            ("Delete / Backspace", "delete the selection"),
            ("Ctrl+A", "select everything shown"),
            ("Ctrl+C / Ctrl+X / Ctrl+V", "copy / cut / paste at the pointer"),
            ("Arrow keys", "move the selection one tile"),
            ("Shift+Arrow keys", "move the selection one sub-unit (1/8 tile)"),
            ("Esc", "cancel a drag (things go back), else clear the selection"),
            ("+ / -", "zoom in / out"),
            ("0", "fit the map in the window"),
        ]),
        ("Mouse on the map", [
            ("Click (Select)", "select; click again on the same spot for the next thing under it"),
            ("Shift+click (Select)", "add to / remove from the selection"),
            ("Drag (Select)", "move the selection by tiles; Shift+drag for sub-units; on empty map: box select"),
            ("Double-click a warp", "open its destination map"),
            ("Ctrl+click a warp", "open its destination map"),
            ("Right-click (Select)", "menu for the thing under the pointer (Duplicate, Copy, Paste here ...)"),
            ("Right-click (Paint / Fill / Rectangle)", "take that tile's value"),
            ("Shift+click (Paint)", "a straight line from the last painted tile"),
            ("Wheel", "zoom at the pointer (or scroll: Options → Map editor)"),
            ("Ctrl+wheel", "the other one of zoom / scroll"),
            ("Shift+wheel", "scroll sideways"),
            ("Middle-drag", "pan"),
            ("Hold Alt over the map", "show the tile's collision (ATTR) and what is there"),
        ]),
        ("Side panels", [
            ("Double-click an object (Objects tab)", "open it in the Inspect tab"),
            ("Delete (Objects tab)", "delete the selected object"),
            ("Right-click an object (Objects tab)", "Show on map / Open in Inspector / Delete"),
            ("Click / drag on the minimap", "move the view there; another room opens that map"),
            ("Right-click an object (palette)", "add to / remove from favourites"),
        ]),
    ]),
    ("Cutscene Editor", [
        ("Anywhere in the editor", [
            ("Ctrl+S", "save into the game folder"),
            ("Ctrl+R", "save and put the scenes, dialogue and em.bin into the game the debugger is attached to"),
            ("F5", "reload rf3.mc, its dialogue and em.bin from disk (drops unsaved edits after asking)"),
            ("Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z)", "undo / redo"),
            ("Ctrl+F", "go to the scene search box"),
            ("Enter in the scene search box", "search"),
            ("Esc in a dialog", "close it"),
        ]),
        ("Script view (click a line first)", [
            ("Up / Down, Page Up / Page Down, Home / End", "move between lines"),
            ("Enter, or double-click a line", "edit it in the Inspector"),
            ("Insert", "add an instruction after (or, chosen in the window, before) the selected line"),
            ("Delete", "delete the selected line(s)"),
            ("F9", "set / remove a breakpoint for the script debugger"),
            ("Ctrl+C", "copy the selected line(s)"),
            ("Ctrl+A", "select every line"),
            ("Shift+click, Shift+Up / Down", "select a range of lines"),
            ("Ctrl+click", "add / remove one line from the selection"),
            ("Right-click", "add an instruction, copy, delete, toggle a breakpoint"),
            ("Hold Alt over a line", "explain the instruction"),
        ]),
        ("Inspector and dialogs", [
            ("Ctrl+Enter in the dialogue box", "apply the text (so does leaving the box)"),
            ("Ctrl+Enter in an Add dialog", "add it"),
            ("Ctrl+Enter in the instruction picker", "insert the instruction"),
            ("Enter in a trigger's fields (Triggers tab)", "apply the keys"),
            ("Double-click / Enter on a trigger", "open its scene"),
            ("Double-click / Enter in Find a line", "use that line"),
            ("Double-click in Callers", "go to the calling statement"),
        ]),
        ("Graph tab", [
            ("Click a block", "select it and highlight the arrows into and out of it"),
            ("Drag a block", "move it (Reset layout puts every block back)"),
            ("Drag the background", "pan"),
            ("Double-click a statement", "go to it in the Script tab"),
            ("Wheel", "zoom at the pointer"),
            ("Ctrl+wheel / Shift+wheel", "scroll up and down / sideways"),
        ]),
        ("Script debugger (🐞 Debug → Debugger…)", [
            ("F9 in the Script view", "set / remove a breakpoint on the selected statement"),
            ("Double-click a breakpoint", "open its statement"),
            ("Double-click a variable (Variables tab)", "open the first statement that uses it"),
            ("Double-click its value / Enter / F2 (Variables tab)",
             "edit the value in place: Enter sets it in the running game, Esc cancels"),
            ("Double-click a text slot (Text slots tab)", "open the first statement that sets or shows it"),
        ]),
        ("Bank listing tab (Options → Advanced)", [
            ("Enter / Shift+Enter in Find", "next / previous match"),
            ("Double-click a line", "open that scene at that statement"),
        ]),
        ("Reference window", [
            ("Double-click / Enter on a row", "copy the name or code (Functions: open it in the "
                                              "instruction picker)"),
        ]),
        ("Map pickers (position / box)", [
            ("Click", "place the point (drag: draw the box)"),
            ("Double-click (position)", "place and use it"),
            ("Wheel, Ctrl+wheel, Shift+wheel, middle-drag, Alt", "as on the map editor's map"),
        ]),
    ]),
    ("Event Manager & text", [
        ("Event Manager window", [
            ("Ctrl+S", "save"),
            ("Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z)", "undo / redo (shared with the Cutscene Editor)"),
            ("Ctrl+F", "go to the search box"),
            ("Enter in the search box", "open the first match"),
            ("Up / Down", "move between lines"),
            ("Enter, or double-click a line", "open what it refers to (the scene, entry or target)"),
            ("Delete", "remove the selected requirement / action / way"),
            ("Hold Alt over a line", "show its raw form and details"),
        ]),
        ("Text editor (explorer tab)", [
            ("Ctrl+Enter", "apply the line"),
            ("Enter / Esc in the New key prompt", "OK / cancel"),
        ]),
    ]),
]


def open_help(parent):
    """The Help window (one per app: a second call brings it forward)."""
    top = parent.winfo_toplevel()
    win = getattr(top, "_shortcuts_help", None)
    if win is not None and win.winfo_exists():
        win.deiconify()
        win.lift()
        return win
    win = tk.Toplevel(top)
    top._shortcuts_help = win
    win.title("Help — shortcuts")
    win.geometry("820x560")
    nb = ttk.Notebook(win)
    nb.pack(fill="both", expand=True, padx=8, pady=8)
    for title, sections in SHORTCUTS:
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text=title)
        tv = ttk.Treeview(f, columns=("what",), show="tree headings")
        tv.heading("#0", text="Shortcut")
        tv.heading("what", text="Action")
        tv.column("#0", width=300, stretch=False)
        tv.column("what", width=460)
        sb = ttk.Scrollbar(f, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tv.pack(fill="both", expand=True)
        tv.tag_configure("section", font=("Segoe UI", 9, "bold"))
        for name, rows in sections:
            parent_id = ""
            if name:
                parent_id = tv.insert("", "end", text=name, open=True, tags=("section",))
            for keys, what in rows:
                tv.insert(parent_id, "end", text=keys, values=(what,))
    bar = ttk.Frame(win)
    bar.pack(fill="x", padx=8, pady=(0, 8))
    ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
    win.bind("<Escape>", lambda _e: win.destroy())
    win.notebook = nb
    return win
