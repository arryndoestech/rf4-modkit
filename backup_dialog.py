"""backup_dialog.py -- put a backed-up version of a game file back.

Every save of a game file keeps its original (the first time) and the file as it was before
the save as a previous version (rf4s_modkit.gamepaths.backup_before_write; how many is an
Option). This window lists them per file, newest first, and restores the one picked. The
file as it is then is kept as a previous version first, so a restore can be undone the same way.
"""
from __future__ import annotations

import datetime
import os
import pathlib
import tkinter as tk
from tkinter import ttk, messagebox

from rf4s_modkit import gamepaths


def _when(path, original=False):
    if original:
        return "original (before the first save)"
    stamp = path.name.rpartition(".")[2]
    try:
        d = datetime.datetime.strptime(stamp[:17], "%Y-%m-%d_%H%M%S")
        return "saved over on %s" % d.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return stamp


def _size(path):
    n = path.stat().st_size
    return "%.1f KB" % (n / 1024) if n < 1024 * 1024 else "%.1f MB" % (n / 1048576)


def open_folder():
    root = gamepaths.backup_root()
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        os.startfile(str(root))                          # noqa: S606 -- the user's own folder


def open_restore(parent, names=None, on_restored=None, answer=None):
    """The restore window. `names` = the file names to list (all backed-up files by default);
    on_restored(game path) after a restore. `answer` (tests): pre-answers the confirmation."""
    win = tk.Toplevel(parent)
    win.title("Restore a previous version")
    win.transient(parent.winfo_toplevel())
    win.geometry("820x420")
    f = ttk.Frame(win, padding=10)
    f.pack(fill="both", expand=True)
    ttk.Label(f, wraplength=780, justify="left", foreground="#666", text=(
        "Pick a version and click Restore to put it back over the game file. Which versions are "
        "kept is set in Options → Advanced.")).pack(anchor="w", pady=(0, 6))
    tv = ttk.Treeview(f, columns=("when", "size"), show="tree headings", height=14)
    tv.heading("#0", text="file / version")
    tv.heading("when", text="version")
    tv.heading("size", text="size")
    tv.column("#0", width=380)
    tv.column("when", width=280)
    tv.column("size", width=90, anchor="e")
    sb = ttk.Scrollbar(f, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    tv.pack(fill="both", expand=True)
    rows = {}
    game = gamepaths.find_bundle_dir()
    base = game.parent if game is not None else None

    def fill():
        tv.delete(*tv.get_children())
        rows.clear()
        files = gamepaths.backed_up_files()
        for target in sorted(files, key=lambda t: t.name.lower()):
            if names and target.name not in names:
                continue
            e = files[target]
            label = str(target.relative_to(base)) if base and base in target.parents else str(target)
            top = tv.insert("", "end", text=label, open=True)
            for pv in e["previous"]:
                iid = tv.insert(top, "end", text="  " + pv.name, values=(_when(pv), _size(pv)))
                rows[iid] = (target, pv)
            if e["original"] is not None:
                iid = tv.insert(top, "end", text="  " + e["original"].name,
                                values=(_when(e["original"], True), _size(e["original"])))
                rows[iid] = (target, e["original"])
        if not rows:
            tv.insert("", "end", text="(no backups yet)")
    fill()
    status = ttk.Label(f, text="", foreground="#666")
    bar = ttk.Frame(f)
    bar.pack(fill="x", pady=(8, 0))

    def restore():
        sel = tv.selection()
        if not sel or sel[0] not in rows:
            status.config(text="pick a version first")
            return None
        target, src = rows[sel[0]]
        kept = ("The file as it is now is kept as a previous version." if gamepaths.keep_previous() > 0
                else "The file as it is now is not kept (previous versions are off in Options).")
        ok = answer if answer is not None else messagebox.askyesno(
            "Restore", "Put this version back as\n%s?\n\n%s\n\n%s"
                       % (target, _when(src, src == gamepaths.backup_path(target)), kept),
            parent=win)
        if not ok:
            return None
        try:
            gamepaths.restore_version(target, src)
        except OSError as e:
            messagebox.showerror("Restore", "Could not restore %s:\n%s" % (target.name, e), parent=win)
            return None
        status.config(text="Restored %s (%s). Reopen it where it is open; restart the game to see it."
                      % (target.name, _when(src, src == gamepaths.backup_path(target))))
        fill()
        if on_restored:
            on_restored(target)
        return target
    ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
    ttk.Button(bar, text="Open backup folder", command=open_folder).pack(side="right", padx=4)
    ttk.Button(bar, text="Restore", command=restore).pack(side="right")
    status.pack(anchor="w", pady=(6, 0))
    win.bind("<Escape>", lambda _e: win.destroy())
    win.restore = restore                               # (tests)
    win.tree = tv
    win.rows = rows
    return win
